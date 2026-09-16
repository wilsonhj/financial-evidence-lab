"""Offline Responses API boundary tests; no credentials or network."""

import json
import traceback
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

from fel_providers.interfaces import StructuredGenerationRequest
from fel_providers.openai_structured import OpenAIStructuredError, OpenAIStructuredProvider

MODEL = "gpt-4.1-2025-04-14"
SECRET = "synthetic-private-marker"
SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}
REQUEST = StructuredGenerationRequest(
    "answer", "v1", SCHEMA, [{"role": "user", "content": SECRET}], 100
)


def validate(schema, value):
    assert schema == SCHEMA
    if set(value) != {"value"} or not isinstance(value["value"], str):
        raise ValueError(SECRET)


def response():
    return {
        "id": "resp_test",
        "model": MODEL,
        "status": "completed",
        "error": None,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 5,
            "total_tokens": 25,
            "input_tokens_details": {"cached_tokens": 10},
        },
    }


def provider(handler, **kwargs):
    def streamed(request):
        result = handler(request)
        # Real HTTP transports return an unread stream; Response(json=...) in
        # test handlers is eagerly consumed, so present the same wire lifecycle.
        if result.is_stream_consumed:
            return httpx.Response(
                result.status_code, headers=result.headers, stream=httpx.ByteStream(result.content)
            )
        return result

    return OpenAIStructuredProvider(
        api_key=SECRET,
        model=MODEL,
        input_price_per_million=Decimal("2"),
        cached_input_price_per_million=Decimal("1"),
        output_price_per_million=Decimal("8"),
        validate_output=validate,
        transport=httpx.MockTransport(streamed),
        **kwargs,
    )


def test_request_and_cost():
    seen = []

    def handler(request):
        seen.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["stream"] is False
        assert body["text"]["format"] == {
            "type": "json_schema",
            "name": "answer",
            "strict": True,
            "schema": SCHEMA,
        }
        assert body["max_output_tokens"] == 100
        return httpx.Response(200, json=response())

    client = provider(handler)
    result = client.generate_structured(REQUEST)
    assert result.parsed == {"value": "ok"}
    assert result.estimated_cost_usd == Decimal("0.000070")
    assert (result.input_tokens, result.output_tokens) == (20, 5)
    assert SECRET not in repr(client) + repr(result.raw)
    assert len(seen) == 1


@pytest.mark.parametrize("status", [401, 429, 500, 503, 302])
def test_http_failures_never_retry_or_expose_body(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, text=SECRET, headers={"location": "https://evil.invalid"})

    with pytest.raises(OpenAIStructuredError) as caught:
        provider(handler).generate_structured(REQUEST)
    assert len(calls) == 1
    assert caught.value.estimated_cost_usd is None
    assert SECRET not in "".join(traceback.format_exception(caught.value))


def test_network_error_does_not_chain_hostile_diagnostics():
    def handler(request):
        raise httpx.ReadError(SECRET, request=request)

    with pytest.raises(OpenAIStructuredError) as caught:
        provider(handler).generate_structured(REQUEST)
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "text",
    ['{"value":2}', '{"value":NaN}', '{"value":1,"value":2}', "[]", "{broken", '{"value":1e999}'],
)
def test_invalid_output_keeps_known_billable_usage(text):
    data = response()
    data["output"][0]["content"][0]["text"] = text
    with pytest.raises(OpenAIStructuredError) as caught:
        provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST)
    assert caught.value.input_tokens == 20
    assert caught.value.estimated_cost_usd == Decimal("0.000070")
    assert SECRET not in "".join(traceback.format_exception(caught.value))


def test_refusal_is_sanitized_and_metered():
    data = response()
    data["output"][0]["content"] = [{"type": "refusal", "refusal": SECRET}]
    result = provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST)
    assert result.refused and result.parsed is None
    assert SECRET not in repr(result)
    assert result.estimated_cost_usd == Decimal("0.000070")


@pytest.mark.parametrize(
    "change",
    [{"status": "incomplete"}, {"model": "other"}, {"error": {"message": SECRET}}, {"output": []}],
)
def test_incomplete_and_bad_envelopes(change):
    data = response() | change
    with pytest.raises(OpenAIStructuredError) as caught:
        provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST)
    assert caught.value.input_tokens == 20


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": True},
        {"input_tokens": 20, "output_tokens": -1, "total_tokens": 19},
        {"input_tokens": 20, "output_tokens": 5, "total_tokens": 24},
        {
            "input_tokens": 20,
            "output_tokens": 5,
            "total_tokens": 25,
            "input_tokens_details": {"cached_tokens": 21},
        },
    ],
)
def test_unknown_usage_is_not_zero(usage):
    data = response() | {"usage": usage}
    with pytest.raises(OpenAIStructuredError) as caught:
        provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST)
    assert caught.value.estimated_cost_usd is None


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, 100001])
def test_invalid_budget_never_sends(budget):
    def handler(_):
        pytest.fail("request must not be sent")

    with pytest.raises(OpenAIStructuredError):
        provider(handler).generate_structured(replace(REQUEST, max_output_tokens=budget))


def test_response_size_limit():
    with pytest.raises(OpenAIStructuredError):
        provider(
            lambda _: httpx.Response(200, content=b"x" * 1025), max_response_bytes=1024
        ).generate_structured(REQUEST)


def test_duplicate_envelope_is_rejected():
    with pytest.raises(OpenAIStructuredError):
        provider(
            lambda _: httpx.Response(200, content=b'{"status":1,"status":2}')
        ).generate_structured(REQUEST)


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", ""),
        ("api_key", "bad\nkey"),
        ("model", "gpt-4.1"),
        ("input_price_per_million", Decimal("NaN")),
        ("input_price_per_million", Decimal("-1")),
        ("input_price_per_million", 2.0),
        ("max_response_bytes", True),
        ("max_response_bytes", 0),
    ],
)
def test_constructor_rejects_invalid_configuration(field, value):
    args = dict(
        api_key=SECRET,
        model=MODEL,
        input_price_per_million=Decimal("2"),
        cached_input_price_per_million=Decimal("1"),
        output_price_per_million=Decimal("8"),
        validate_output=validate,
    )
    args[field] = value
    with pytest.raises(ValueError, match="Invalid OpenAI adapter configuration"):
        OpenAIStructuredProvider(**args)


@pytest.mark.parametrize("returned", [False, True, {"valid": True}])
def test_validator_must_return_none(returned):
    adapter = provider(lambda _: httpx.Response(200, json=response()))
    adapter._validate = lambda schema, parsed: returned
    with pytest.raises(OpenAIStructuredError) as caught:
        adapter.generate_structured(REQUEST)
    assert caught.value.estimated_cost_usd == Decimal("0.000070")


def test_environment_key_and_proxy_never_replace_explicit_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-the-injected-key")
    monkeypatch.setenv("HTTPS_PROXY", "https://invalid.invalid")

    def handler(request):
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(200, json=response())

    assert provider(handler).generate_structured(REQUEST).parsed == {"value": "ok"}


@pytest.mark.parametrize(
    "change",
    [
        {"temperature": float("nan")},
        {"temperature": True},
        {"messages": [{"role": "tool", "content": SECRET}]},
        {"messages": [{"role": "user", "content": SECRET, "secret": SECRET}]},
        {"json_schema": {"type": "object", "const": float("inf")}},
        {"schema_name": SECRET + "!"},
    ],
)
def test_invalid_input_is_safe_and_never_sent(change):
    def handler(_):
        pytest.fail("must not send invalid input")

    with pytest.raises(OpenAIStructuredError) as caught:
        provider(handler).generate_structured(replace(REQUEST, **change))
    assert SECRET not in "".join(traceback.format_exception(caught.value))


def test_reasoning_item_is_not_returned_as_raw_metadata():
    data = response()
    data["output"].insert(0, {"type": "reasoning", "summary": SECRET})
    assert SECRET not in repr(
        provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST).raw
    )


def test_mixed_refusal_and_text_fails_closed():
    data = response()
    data["output"][0]["content"].append({"type": "refusal", "refusal": SECRET})
    with pytest.raises(OpenAIStructuredError):
        provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST)


def test_output_usage_exceeding_budget_is_rejected_but_accounted():
    data = response()
    data["usage"]["output_tokens"] = 101
    data["usage"]["total_tokens"] = 121
    with pytest.raises(OpenAIStructuredError) as caught:
        provider(lambda _: httpx.Response(200, json=data)).generate_structured(REQUEST)
    assert caught.value.output_tokens == 101
    assert caught.value.estimated_cost_usd == Decimal("0.000838")


def test_cost_ignores_ambient_decimal_precision():
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 1
        result = provider(lambda _: httpx.Response(200, json=response())).generate_structured(
            REQUEST
        )
    assert result.estimated_cost_usd == Decimal("0.000070")


def test_elapsed_body_deadline(monkeypatch):
    from fel_providers import openai_structured

    ticks = iter([0.0, 61.0])
    monkeypatch.setattr(openai_structured.time, "monotonic", lambda: next(ticks))
    with pytest.raises(OpenAIStructuredError) as caught:
        provider(lambda _: httpx.Response(200, json=response())).generate_structured(REQUEST)
    assert caught.value.code == "response_timeout"


def test_compressed_response_is_rejected():
    with pytest.raises(OpenAIStructuredError):
        provider(
            lambda _: httpx.Response(200, json=response(), headers={"content-encoding": "br"})
        ).generate_structured(REQUEST)


def test_slow_drip_checks_deadline_on_each_transport_chunk(monkeypatch):
    from fel_providers import openai_structured

    elapsed = [0]

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(5000):
                elapsed[0] += 1
                yield b" "

    monkeypatch.setattr(openai_structured.time, "monotonic", lambda: elapsed[0])
    with pytest.raises(OpenAIStructuredError) as caught:
        provider(lambda _: httpx.Response(200, stream=SlowStream())).generate_structured(REQUEST)
    assert caught.value.code == "response_timeout"
    assert elapsed[0] == 61
