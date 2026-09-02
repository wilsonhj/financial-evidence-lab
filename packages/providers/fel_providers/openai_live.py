"""Live OpenAI adapters behind the frozen provider protocols (ADR-0012, #195).

Two adapters, both pure ``httpx`` with an injectable transport/clock:

* :class:`OpenAIStructuredProvider` implements ``StructuredLLMProvider`` against
  the **Responses API** (``POST /v1/responses``) with
  ``text.format = {"type": "json_schema", "strict": true, ...}``, the documented
  way to constrain output to a JSON Schema. A fallback path behind
  ``use_chat_completions`` speaks **Chat Completions**
  (``POST /v1/chat/completions``) with the equivalent
  ``response_format = {"type": "json_schema", ...}``; it exists so an operator
  can route around a Responses-API problem without a code change, and is not the
  default.
* :class:`OpenAIEmbeddingProvider` implements ``EmbeddingProvider`` against
  ``POST /v1/embeddings`` with ``dimensions=512`` — ``halfvec(512)`` is a storage
  contract (ADR-0002), so any other width is a hard failure here rather than a
  silent truncation downstream.

Refusals map to ``StructuredModelResult(refused=True, parsed=None)``: a model
that declines is a first-class outcome the run records, never an exception and
never an empty answer that reads like a real one. Output that is not JSON, or is
JSON that does not satisfy the requested schema, raises
:class:`ProviderProtocolError` (fail closed).

The API key is read from ``FEL_OPENAI_API_KEY`` by :mod:`fel_providers.factory`
and passed in; nothing here reads the environment directly, and nothing here
logs, stores, or embeds prompt or completion text in an exception.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import httpx

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_providers.live_http import (
    LiveHttpConfig,
    ProviderConfigurationError,
    ProviderProtocolError,
    RetryingJsonClient,
)
from fel_providers.schema_check import schema_errors

OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
# ADR-0002 stores embeddings as halfvec(512); the request pins the width so the
# provider never decides the storage contract.
EMBEDDING_DIMENSIONS = 512

PROVIDER_NAME = "openai"


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key.strip():
        raise ProviderConfigurationError("FEL_OPENAI_API_KEY is empty")
    return {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


def _estimated_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_usd_per_mtok: Decimal,
    output_usd_per_mtok: Decimal,
) -> Decimal:
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * input_usd_per_mtok + Decimal(output_tokens) * output_usd_per_mtok
    ) / million


def _require_int(container: Mapping[str, Any], key: str) -> int:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderProtocolError(f"usage.{key} missing or not an integer in provider response")
    return value


def _schema_format_name(request: StructuredGenerationRequest) -> str:
    return f"{request.schema_name}_{request.schema_version}".replace("-", "_")


class OpenAIStructuredProvider:
    """``StructuredLLMProvider`` over the OpenAI Responses API.

    ``use_chat_completions=True`` selects the documented Chat Completions
    ``response_format`` path instead; both paths use documented fields only.
    """

    provider = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = OPENAI_BASE_URL,
        config: LiveHttpConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        use_chat_completions: bool = False,
        input_usd_per_mtok: Decimal = Decimal("0"),
        output_usd_per_mtok: Decimal = Decimal("0"),
    ) -> None:
        self.model = model
        self._use_chat_completions = use_chat_completions
        self._input_usd_per_mtok = input_usd_per_mtok
        self._output_usd_per_mtok = output_usd_per_mtok
        self._client = RetryingJsonClient(
            base_url=base_url,
            headers=_auth_headers(api_key),
            config=config,
            transport=transport,
            sleep=sleep,
            monotonic=monotonic,
        )

    def close(self) -> None:
        self._client.close()

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        if request.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be >= 1")
        if self._use_chat_completions:
            return self._chat_completions(request)
        return self._responses(request)

    # -- Responses API (default) -------------------------------------------
    def _responses(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": message["role"], "content": message["content"]}
                for message in request.messages
            ],
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _schema_format_name(request),
                    "strict": True,
                    "schema": request.json_schema,
                }
            },
        }
        body = self._client.post_json("/responses", payload)
        text, refusal = _responses_output(body)
        return self._result(request, body, text=text, refusal=refusal)

    # -- Chat Completions (fallback path behind a flag) --------------------
    def _chat_completions(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": message["role"], "content": message["content"]}
                for message in request.messages
            ],
            "max_completion_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_format_name(request),
                    "strict": True,
                    "schema": request.json_schema,
                },
            },
        }
        body = self._client.post_json("/chat/completions", payload)
        text, refusal = _chat_output(body)
        return self._result(request, body, text=text, refusal=refusal)

    def _result(
        self,
        request: StructuredGenerationRequest,
        body: Mapping[str, Any],
        *,
        text: str | None,
        refusal: str | None,
    ) -> StructuredModelResult:
        usage_raw = body.get("usage")
        if not isinstance(usage_raw, dict):
            raise ProviderProtocolError("provider response has no usage object")
        if self._use_chat_completions:
            input_tokens = _require_int(usage_raw, "prompt_tokens")
            output_tokens = _require_int(usage_raw, "completion_tokens")
        else:
            input_tokens = _require_int(usage_raw, "input_tokens")
            output_tokens = _require_int(usage_raw, "output_tokens")
        response_id = str(body.get("id") or "")
        model = str(body.get("model") or self.model)
        cost = _estimated_cost(
            input_tokens,
            output_tokens,
            input_usd_per_mtok=self._input_usd_per_mtok,
            output_usd_per_mtok=self._output_usd_per_mtok,
        )
        raw: dict[str, object] = {
            "provider": self.provider,
            "model": model,
            "response_id": response_id,
            "endpoint": "chat.completions" if self._use_chat_completions else "responses",
            "refused": refusal is not None,
        }
        if refusal is not None:
            return StructuredModelResult(
                provider=self.provider,
                model=model,
                response_id=response_id,
                parsed=None,
                refused=True,
                # The refusal string is short categorical model output required
                # by the protocol; it is carried on the result and never logged.
                refusal=refusal,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
                raw=raw,
            )
        parsed = _parse_and_validate(text, request.json_schema)
        return StructuredModelResult(
            provider=self.provider,
            model=model,
            response_id=response_id,
            parsed=parsed,
            refused=False,
            refusal=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            raw=raw,
        )


def _parse_and_validate(text: str | None, schema: Mapping[str, Any]) -> dict[str, object]:
    if text is None:
        raise ProviderProtocolError("provider response contained no output text")
    try:
        loaded = json.loads(text)
    except ValueError as exc:
        raise ProviderProtocolError("provider output is not valid JSON") from exc
    if not isinstance(loaded, dict):
        raise ProviderProtocolError(
            f"provider output is a JSON {type(loaded).__name__}, expected an object"
        )
    errors = schema_errors(loaded, dict(schema))
    if errors:
        # Error text names schema locations and types only, never values.
        raise ProviderProtocolError(f"provider output failed schema validation: {errors[0]}")
    return loaded


def _responses_output(body: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Extract ``(output_text, refusal)`` from a Responses API body."""
    output = body.get("output")
    if not isinstance(output, list):
        raise ProviderProtocolError("Responses body has no output array")
    chunks: list[str] = []
    for entry in output:
        if not isinstance(entry, dict) or entry.get("type") != "message":
            continue
        content = entry.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "refusal":
                refusal = block.get("refusal")
                return None, str(refusal) if refusal is not None else "refused"
            if block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    if not chunks:
        return None, None
    return "".join(chunks), None


def _chat_output(body: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Extract ``(content, refusal)`` from a Chat Completions body."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderProtocolError("Chat Completions body has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderProtocolError("Chat Completions choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ProviderProtocolError("Chat Completions choice has no message")
    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal:
        return None, refusal
    content = message.get("content")
    return (content if isinstance(content, str) else None), None


class OpenAIEmbeddingProvider:
    """``EmbeddingProvider`` over ``POST /v1/embeddings``, pinned to 512 dims."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
        base_url: str = OPENAI_BASE_URL,
        config: LiveHttpConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if dimensions > EMBEDDING_DIMENSIONS:
            raise ProviderConfigurationError(
                f"ADR-0002 caps embedding dimensions at {EMBEDDING_DIMENSIONS}"
            )
        if dimensions < 1:
            raise ProviderConfigurationError("dimensions must be >= 1")
        self.dimensions = dimensions
        self.model = model
        self._client = RetryingJsonClient(
            base_url=base_url,
            headers=_auth_headers(api_key),
            config=config,
            transport=transport,
            sleep=sleep,
            monotonic=monotonic,
        )

    def close(self) -> None:
        self._client.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts``; fail closed on any width other than ``dimensions``."""
        if not texts:
            return []
        body = self._client.post_json(
            "/embeddings",
            {"model": self.model, "input": list(texts), "dimensions": self.dimensions},
        )
        data = body.get("data")
        if not isinstance(data, list):
            raise ProviderProtocolError("embeddings body has no data array")
        if len(data) != len(texts):
            raise ProviderProtocolError(
                f"embeddings returned {len(data)} vectors for {len(texts)} inputs"
            )
        vectors = _ordered_embeddings(data, expected=len(texts))
        for index, vector in enumerate(vectors):
            if len(vector) != self.dimensions:
                raise ProviderProtocolError(
                    f"embedding {index} has {len(vector)} dims, expected {self.dimensions}"
                )
        return vectors


def _ordered_embeddings(data: Sequence[Any], *, expected: int) -> list[list[float]]:
    """Return vectors in input order; the API returns an explicit ``index``."""
    slots: list[list[float] | None] = [None] * expected
    for position, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ProviderProtocolError("embeddings data entry is not an object")
        raw_index = entry.get("index", position)
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ProviderProtocolError("embeddings data entry has a non-integer index")
        if not 0 <= raw_index < expected:
            raise ProviderProtocolError("embeddings data entry index is out of range")
        embedding = entry.get("embedding")
        if not isinstance(embedding, list):
            raise ProviderProtocolError("embeddings data entry has no embedding array")
        floats: list[float] = []
        for component in embedding:
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise ProviderProtocolError("embedding component is not a number")
            floats.append(float(component))
        if slots[raw_index] is not None:
            raise ProviderProtocolError("embeddings data contains a duplicate index")
        slots[raw_index] = floats
    result: list[list[float]] = []
    for slot in slots:
        if slot is None:
            raise ProviderProtocolError("embeddings data is missing an input index")
        result.append(slot)
    return result


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_MODEL",
    "EMBEDDING_DIMENSIONS",
    "OPENAI_BASE_URL",
    "OpenAIEmbeddingProvider",
    "OpenAIStructuredProvider",
]
