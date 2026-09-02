"""Contract tests for the live adapters (ADR-0012 / #195).

Every request is served by an ``httpx.MockTransport`` over a recorded response
shape; the clock is a fake, so nothing here sleeps and nothing here touches the
network. Each adapter is exercised on the six paths the issue names: schema-valid
happy path, refusal, 429-then-success, malformed JSON, missing key (fails
closed), and — for embeddings — a dimension mismatch.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from fel_providers.anthropic_live import (
    STRUCTURED_TOOL_NAME,
    AnthropicStructuredProvider,
)
from fel_providers.interfaces import StructuredGenerationRequest
from fel_providers.live_http import (
    LiveHttpConfig,
    ProviderConfigurationError,
    ProviderHttpError,
    ProviderProtocolError,
)
from fel_providers.openai_live import OpenAIEmbeddingProvider, OpenAIStructuredProvider

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {"text": {"type": "string", "minLength": 1}},
            },
        }
    },
}
VALID_OUTPUT: dict[str, Any] = {"claims": [{"text": "Revenue was $100 million."}]}

REQUEST = StructuredGenerationRequest(
    schema_name="claims-output",
    schema_version="v1",
    json_schema=SCHEMA,
    messages=[
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "question and context"},
    ],
    max_output_tokens=256,
)


class Clock:
    """Fake clock: records every sleep, advances monotonic time."""

    def __init__(self) -> None:
        self.slept: list[float] = []
        self._now = 0.0

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self._now += seconds

    def monotonic(self) -> float:
        return self._now


def _openai(
    handler: Any, *, clock: Clock | None = None, use_chat_completions: bool = False
) -> OpenAIStructuredProvider:
    clock = clock or Clock()
    return OpenAIStructuredProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        config=LiveHttpConfig(max_retries=2),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        use_chat_completions=use_chat_completions,
        input_usd_per_mtok=Decimal("2"),
        output_usd_per_mtok=Decimal("8"),
    )


def _anthropic(handler: Any, *, clock: Clock | None = None) -> AnthropicStructuredProvider:
    clock = clock or Clock()
    return AnthropicStructuredProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        config=LiveHttpConfig(max_retries=2),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def _responses_body(text: str) -> dict[str, Any]:
    return {
        "id": "resp_123",
        "model": "gpt-4.1-2025-04-14",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {"input_tokens": 120, "output_tokens": 34},
    }


def _messages_body(tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "msg_123",
        "model": "claude-opus-4-8",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": STRUCTURED_TOOL_NAME,
                "input": tool_input,
            }
        ],
        "usage": {"input_tokens": 200, "output_tokens": 40},
    }


# --- OpenAI: Responses API -------------------------------------------------
def test_openai_happy_path_parses_and_records_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=_responses_body(json.dumps(VALID_OUTPUT)))

    result = _openai(handler).generate_structured(REQUEST)

    assert seen["url"].endswith("/v1/responses")
    assert seen["auth"] == "Bearer test-key"
    text_format = seen["body"]["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"] == SCHEMA
    assert seen["body"]["max_output_tokens"] == 256

    assert result.provider == "openai"
    assert result.model == "gpt-4.1-2025-04-14"
    assert result.response_id == "resp_123"
    assert result.refused is False
    assert result.parsed == VALID_OUTPUT
    assert result.input_tokens == 120
    assert result.output_tokens == 34
    # 120/1e6*2 + 34/1e6*8 exactly, in Decimal.
    assert result.estimated_cost_usd == Decimal("0.000512")


def test_openai_refusal_maps_to_refused_result() -> None:
    body = _responses_body("")
    body["output"] = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "refusal", "refusal": "I can't help with that."}],
        }
    ]

    result = _openai(lambda _r: httpx.Response(200, json=body)).generate_structured(REQUEST)

    assert result.refused is True
    assert result.parsed is None
    assert result.refusal == "I can't help with that."
    assert result.output_tokens == 34


def test_openai_retries_429_then_succeeds_and_honours_retry_after() -> None:
    clock = Clock()
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "7"}, json={"error": "slow down"})
        return httpx.Response(200, json=_responses_body(json.dumps(VALID_OUTPUT)))

    result = _openai(handler, clock=clock).generate_structured(REQUEST)

    assert len(calls) == 2
    assert result.parsed == VALID_OUTPUT
    # The Retry-After wins over the 0.5s exponential backoff for that attempt.
    assert clock.slept == [7.0]


def test_openai_retries_exhausted_raises_http_error() -> None:
    clock = Clock()
    provider = _openai(lambda _r: httpx.Response(503), clock=clock)
    with pytest.raises(ProviderHttpError) as excinfo:
        provider.generate_structured(REQUEST)
    assert excinfo.value.status_code == 503
    assert clock.slept == [0.5, 1.0]


def test_openai_client_error_is_not_retried() -> None:
    clock = Clock()
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"error": "bad key"})

    provider = _openai(handler, clock=clock)
    with pytest.raises(ProviderHttpError) as excinfo:
        provider.generate_structured(REQUEST)
    assert excinfo.value.status_code == 401
    assert calls == [1]
    assert clock.slept == []


def test_openai_malformed_json_fails_closed() -> None:
    provider = _openai(lambda _r: httpx.Response(200, json=_responses_body("{not json")))
    with pytest.raises(ProviderProtocolError, match="not valid JSON"):
        provider.generate_structured(REQUEST)


def test_openai_schema_invalid_output_fails_closed() -> None:
    body = _responses_body(json.dumps({"claims": [{"text": "ok", "extra": 1}]}))
    provider = _openai(lambda _r: httpx.Response(200, json=body))
    with pytest.raises(ProviderProtocolError, match="schema validation"):
        provider.generate_structured(REQUEST)


def test_openai_error_text_never_contains_prompt_or_completion() -> None:
    secret_completion = json.dumps({"claims": [{"text": "CONFIDENTIAL REVENUE"}], "x": 1})
    provider = _openai(lambda _r: httpx.Response(200, json=_responses_body(secret_completion)))
    with pytest.raises(ProviderProtocolError) as excinfo:
        provider.generate_structured(REQUEST)
    message = str(excinfo.value)
    assert "CONFIDENTIAL" not in message
    assert "question and context" not in message


def test_openai_missing_key_fails_closed() -> None:
    with pytest.raises(ProviderConfigurationError):
        OpenAIStructuredProvider(api_key="   ")


# --- OpenAI: Chat Completions fallback ------------------------------------
def test_openai_chat_completions_fallback_path() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_1",
                "model": "gpt-4.1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(VALID_OUTPUT)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            },
        )

    result = _openai(handler, use_chat_completions=True).generate_structured(REQUEST)

    assert seen["url"].endswith("/v1/chat/completions")
    response_format = seen["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert result.parsed == VALID_OUTPUT
    assert (result.input_tokens, result.output_tokens) == (11, 5)


def test_openai_chat_completions_refusal() -> None:
    body = {
        "id": "chatcmpl_1",
        "model": "gpt-4.1",
        "choices": [{"index": 0, "message": {"role": "assistant", "refusal": "no"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }
    result = _openai(
        lambda _r: httpx.Response(200, json=body), use_chat_completions=True
    ).generate_structured(REQUEST)
    assert result.refused is True
    assert result.parsed is None


# --- Anthropic -------------------------------------------------------------
def test_anthropic_forced_tool_happy_path() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=_messages_body(VALID_OUTPUT))

    result = _anthropic(handler).generate_structured(REQUEST)

    assert seen["url"].endswith("/v1/messages")
    assert seen["headers"]["x-api-key"] == "test-key"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    # System turns are lifted out of messages; sampling params are not sent.
    assert body["system"] == "system instructions"
    assert body["messages"] == [{"role": "user", "content": "question and context"}]
    assert "temperature" not in body
    assert body["tool_choice"] == {"type": "tool", "name": STRUCTURED_TOOL_NAME}
    assert len(body["tools"]) == 1
    assert body["tools"][0]["input_schema"] == SCHEMA
    assert body["tools"][0]["strict"] is True
    assert body["max_tokens"] == 256

    assert result.provider == "anthropic"
    assert result.parsed == VALID_OUTPUT
    assert result.refused is False
    assert (result.input_tokens, result.output_tokens) == (200, 40)
    assert result.response_id == "msg_123"


def test_anthropic_refusal_stop_reason_maps_to_refused_result() -> None:
    body = {
        "id": "msg_9",
        "model": "claude-opus-4-8",
        "stop_reason": "refusal",
        "stop_details": {"type": "refusal", "category": "cyber", "explanation": "declined"},
        "content": [],
        "usage": {"input_tokens": 12, "output_tokens": 0},
    }
    result = _anthropic(lambda _r: httpx.Response(200, json=body)).generate_structured(REQUEST)
    assert result.refused is True
    assert result.parsed is None
    assert result.refusal == "refusal:cyber"
    assert result.input_tokens == 12


def test_anthropic_retries_429_then_succeeds() -> None:
    clock = Clock()
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"type": "error"})
        return httpx.Response(200, json=_messages_body(VALID_OUTPUT))

    result = _anthropic(handler, clock=clock).generate_structured(REQUEST)
    assert len(calls) == 2
    assert result.parsed == VALID_OUTPUT
    # No Retry-After header: plain exponential backoff.
    assert clock.slept == [0.5]


def test_anthropic_malformed_tool_input_fails_closed() -> None:
    body = _messages_body(VALID_OUTPUT)
    body["content"] = [{"type": "tool_use", "id": "t", "name": STRUCTURED_TOOL_NAME, "input": "{"}]
    provider = _anthropic(lambda _r: httpx.Response(200, json=body))
    with pytest.raises(ProviderProtocolError, match="not a JSON object"):
        provider.generate_structured(REQUEST)


def test_anthropic_schema_invalid_tool_input_fails_closed() -> None:
    body = _messages_body({"claims": [{"text": ""}]})
    provider = _anthropic(lambda _r: httpx.Response(200, json=body))
    with pytest.raises(ProviderProtocolError, match="schema validation"):
        provider.generate_structured(REQUEST)


def test_anthropic_text_only_answer_fails_closed() -> None:
    body = _messages_body(VALID_OUTPUT)
    body["content"] = [{"type": "text", "text": "here you go"}]
    body["stop_reason"] = "end_turn"
    provider = _anthropic(lambda _r: httpx.Response(200, json=body))
    with pytest.raises(ProviderProtocolError, match="no tool_use block"):
        provider.generate_structured(REQUEST)


def test_anthropic_missing_key_fails_closed() -> None:
    with pytest.raises(ProviderConfigurationError):
        AnthropicStructuredProvider(api_key="")


# --- Embeddings ------------------------------------------------------------
def _embeddings(handler: Any, *, dimensions: int = 512) -> OpenAIEmbeddingProvider:
    clock = Clock()
    return OpenAIEmbeddingProvider(
        api_key="test-key",
        dimensions=dimensions,
        transport=httpx.MockTransport(handler),
        config=LiveHttpConfig(max_retries=1),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def _embedding_body(widths: list[int]) -> dict[str, Any]:
    return {
        "object": "list",
        "model": "text-embedding-3-small",
        "data": [
            {"object": "embedding", "index": index, "embedding": [0.1] * width}
            for index, width in enumerate(widths)
        ],
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }


def test_embeddings_pin_512_dimensions_in_the_request() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_embedding_body([512, 512]))

    vectors = _embeddings(handler).embed(["a", "b"])

    assert seen["url"].endswith("/v1/embeddings")
    assert seen["body"]["dimensions"] == 512
    assert seen["body"]["input"] == ["a", "b"]
    assert [len(v) for v in vectors] == [512, 512]


def test_embeddings_dimension_mismatch_fails_closed() -> None:
    provider = _embeddings(lambda _r: httpx.Response(200, json=_embedding_body([256])))
    with pytest.raises(ProviderProtocolError, match="expected 512"):
        provider.embed(["a"])


def test_embeddings_count_mismatch_fails_closed() -> None:
    provider = _embeddings(lambda _r: httpx.Response(200, json=_embedding_body([512])))
    with pytest.raises(ProviderProtocolError, match="vectors for"):
        provider.embed(["a", "b"])


def test_embeddings_are_returned_in_input_order() -> None:
    body = _embedding_body([512, 512])
    body["data"] = [
        {"object": "embedding", "index": 1, "embedding": [0.2] * 512},
        {"object": "embedding", "index": 0, "embedding": [0.1] * 512},
    ]
    vectors = _embeddings(lambda _r: httpx.Response(200, json=body)).embed(["a", "b"])
    assert vectors[0][0] == pytest.approx(0.1)
    assert vectors[1][0] == pytest.approx(0.2)


def test_embeddings_over_cap_dimensions_rejected() -> None:
    with pytest.raises(ProviderConfigurationError, match="caps embedding dimensions"):
        _embeddings(lambda _r: httpx.Response(200, json={}), dimensions=1536)


def test_embeddings_empty_input_makes_no_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request expected for an empty input list")

    assert _embeddings(handler).embed([]) == []


def test_embeddings_missing_key_fails_closed() -> None:
    with pytest.raises(ProviderConfigurationError):
        OpenAIEmbeddingProvider(api_key="")
