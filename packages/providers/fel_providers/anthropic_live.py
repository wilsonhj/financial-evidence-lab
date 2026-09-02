"""Live Anthropic adapter behind the frozen ``StructuredLLMProvider`` (ADR-0012).

Generation only: the Anthropic API ships no embeddings endpoint, so
``EmbeddingProvider`` stays OpenAI-or-mock (see ADR-0012 and
:mod:`fel_providers.openai_live`).

Schema-conformant JSON comes from the documented tool-use path on the Messages
API (``POST /v1/messages``): the request declares exactly **one** tool whose
``input_schema`` is the request's JSON Schema, marks it ``strict`` so arguments
are guaranteed to validate, and forces it with
``tool_choice = {"type": "tool", "name": ...}``. The model's answer is then the
``tool_use`` block's ``input`` object rather than free text, which is the
provider's own recommendation for structured output.

Deliberate omissions, each of which would be a 400 or a behaviour change on the
current model family:

* No ``temperature``/``top_p`` — sampling parameters are rejected by the current
  Anthropic models, so ``StructuredGenerationRequest.temperature`` is not
  forwarded. Determinism is bought by the forced tool schema instead.
* No ``thinking`` block — the adapter takes the model default.
* ``system`` turns are lifted out of ``messages`` into the top-level ``system``
  parameter, which is where the Messages API takes them.

A model that declines answers with HTTP 200 and ``stop_reason == "refusal"``;
that maps to ``StructuredModelResult(refused=True, parsed=None)`` with the
``stop_details`` category recorded, never an exception. Anything else that is
not a schema-valid tool call — no tool block, a non-object input, arguments that
fail the schema — raises :class:`ProviderProtocolError` (fail closed).

The key is read from ``FEL_ANTHROPIC_API_KEY`` by :mod:`fel_providers.factory`
and passed in; nothing here reads the environment, and no prompt or completion
text reaches a log or an exception message.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
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

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-4-8"
# Single forced tool: the name is fixed so the response parser never has to
# trust a model-chosen identifier.
STRUCTURED_TOOL_NAME = "emit_structured_output"

PROVIDER_NAME = "anthropic"


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key.strip():
        raise ProviderConfigurationError("FEL_ANTHROPIC_API_KEY is empty")
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _split_system(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    """Lift ``system`` turns into the top-level parameter, order preserved."""
    system_parts: list[str] = []
    turns: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            raise ProviderConfigurationError(
                f"unsupported message role {role!r} for the Messages API"
            )
        turns.append({"role": role, "content": content})
    if not turns:
        raise ProviderConfigurationError("request has no user/assistant turns")
    return ("\n\n".join(system_parts) if system_parts else None), turns


def _require_int(container: Mapping[str, Any], key: str) -> int:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderProtocolError(f"usage.{key} missing or not an integer in provider response")
    return value


class AnthropicStructuredProvider:
    """``StructuredLLMProvider`` over the Anthropic Messages API (forced tool)."""

    provider = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = ANTHROPIC_BASE_URL,
        config: LiveHttpConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        input_usd_per_mtok: Decimal = Decimal("0"),
        output_usd_per_mtok: Decimal = Decimal("0"),
    ) -> None:
        self.model = model
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
        system, turns = _split_system(list(request.messages))
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "messages": turns,
            "tools": [
                {
                    "name": STRUCTURED_TOOL_NAME,
                    "description": (
                        f"Emit the {request.schema_name} {request.schema_version} object."
                        " This is the only permitted response."
                    ),
                    "input_schema": request.json_schema,
                    "strict": True,
                }
            ],
            "tool_choice": {"type": "tool", "name": STRUCTURED_TOOL_NAME},
        }
        if system is not None:
            payload["system"] = system

        body = self._client.post_json("/messages", payload)

        response_id = str(body.get("id") or "")
        model = str(body.get("model") or self.model)
        usage_raw = body.get("usage")
        if not isinstance(usage_raw, dict):
            raise ProviderProtocolError("provider response has no usage object")
        input_tokens = _require_int(usage_raw, "input_tokens")
        output_tokens = _require_int(usage_raw, "output_tokens")
        million = Decimal(1_000_000)
        cost = (
            Decimal(input_tokens) * self._input_usd_per_mtok
            + Decimal(output_tokens) * self._output_usd_per_mtok
        ) / million
        stop_reason = body.get("stop_reason")
        raw: dict[str, object] = {
            "provider": self.provider,
            "model": model,
            "response_id": response_id,
            "stop_reason": stop_reason,
            "refused": stop_reason == "refusal",
        }

        if stop_reason == "refusal":
            return StructuredModelResult(
                provider=self.provider,
                model=model,
                response_id=response_id,
                parsed=None,
                refused=True,
                refusal=_refusal_label(body),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
                raw=raw,
            )

        parsed = _tool_input(body, request.json_schema)
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


def _refusal_label(body: Mapping[str, Any]) -> str:
    """Categorical refusal label from ``stop_details`` (no free model text)."""
    details = body.get("stop_details")
    if isinstance(details, dict):
        category = details.get("category")
        if isinstance(category, str) and category:
            return f"refusal:{category}"
    return "refusal"


def _tool_input(body: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, object]:
    content = body.get("content")
    if not isinstance(content, list):
        raise ProviderProtocolError("Messages body has no content array")
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != STRUCTURED_TOOL_NAME:
            raise ProviderProtocolError("response used an unexpected tool name")
        arguments = block.get("input")
        if not isinstance(arguments, dict):
            raise ProviderProtocolError("tool_use input is not a JSON object")
        errors = schema_errors(arguments, dict(schema))
        if errors:
            raise ProviderProtocolError(f"provider output failed schema validation: {errors[0]}")
        return arguments
    raise ProviderProtocolError("response contained no tool_use block")


__all__ = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_VERSION",
    "DEFAULT_MODEL",
    "STRUCTURED_TOOL_NAME",
    "AnthropicStructuredProvider",
]
