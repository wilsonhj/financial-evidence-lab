"""Explicit, non-retrying OpenAI Responses adapter; no default runtime binding."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Any

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult

if TYPE_CHECKING:
    import httpx

_ENDPOINT = "https://api.openai.com/v1/responses"
Validator = Callable[[dict[str, object], dict[str, object]], None]
Usage = tuple[int, int, int, Decimal]


class OpenAIStructuredError(RuntimeError):
    """Safe failure; None usage/cost means unknown, never a free request."""

    def __init__(self, code: str, usage: Usage | None = None) -> None:
        super().__init__(f"OpenAI structured generation failed: {code}")
        self.code = code
        self.input_tokens = usage[0] if usage else None
        self.output_tokens = usage[1] if usage else None
        self.cached_input_tokens = usage[2] if usage else None
        self.estimated_cost_usd = usage[3] if usage else None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite JSON")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _json(data: str | bytes) -> Any:
    value = json.loads(data, object_pairs_hook=_object)
    _finite(value)
    return value


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError("invalid usage")
    return int(value)


class OpenAIStructuredProvider:
    """Caller supplies trusted schema validator, snapshot model, credential and prices.

    Validator must raise on mismatch and return exactly None on success. It must
    not mutate the schema or parsed result. HTTPX is imported only when invoked,
    keeping dependency-free provider protocol/mock installations importable.
    """

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        input_price_per_million: Decimal,
        cached_input_price_per_million: Decimal,
        output_price_per_million: Decimal,
        validate_output: Validator,
        transport: httpx.BaseTransport | None = None,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        valid = (
            isinstance(api_key, str)
            and bool(api_key)
            and len(api_key) <= 4096
            and all(33 <= ord(char) <= 126 for char in api_key)
            and isinstance(model, str)
            and re.fullmatch(r"[A-Za-z0-9.-]+-\d{4}-\d{2}-\d{2}", model) is not None
            and callable(validate_output)
            and type(max_response_bytes) is int
            and 1024 <= max_response_bytes <= 8 * 1024 * 1024
        )
        prices = (input_price_per_million, cached_input_price_per_million, output_price_per_million)
        if not valid or any(
            not isinstance(price, Decimal)
            or not price.is_finite()
            or not 0 <= price <= 10**6
            or int(price.as_tuple().exponent) < -12
            for price in prices
        ):
            raise ValueError("Invalid OpenAI adapter configuration")
        self._api_key = api_key
        self.model = model
        self._prices = prices
        self._validate = validate_output
        self._transport = transport
        self._max_response_bytes = max_response_bytes

    def _usage(self, data: dict[str, Any]) -> Usage:
        usage = data["usage"]
        incoming = _count(usage["input_tokens"])
        outgoing = _count(usage["output_tokens"])
        cached = _count(usage["input_tokens_details"]["cached_tokens"])
        if cached > incoming or _count(usage["total_tokens"]) != incoming + outgoing:
            raise ValueError("inconsistent usage")
        with localcontext() as context:
            context.prec = 50
            cost = (
                Decimal(incoming - cached) * self._prices[0]
                + Decimal(cached) * self._prices[1]
                + Decimal(outgoing) * self._prices[2]
            ) / Decimal(1000000)
        return incoming, outgoing, cached, cost

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        # Raise only outside the exception handler: neither cause nor context can
        # retain HTTP request headers, response bodies or validator diagnostics.
        failure: tuple[str, Usage | None] = ("invalid_request", None)
        try:
            return self._generate(request)
        except OpenAIStructuredError as exc:
            usage = None
            if (
                exc.estimated_cost_usd is not None
                and exc.input_tokens is not None
                and exc.output_tokens is not None
                and exc.cached_input_tokens is not None
            ):
                usage = (
                    exc.input_tokens,
                    exc.output_tokens,
                    exc.cached_input_tokens,
                    exc.estimated_cost_usd,
                )
            failure = (exc.code, usage)
        except Exception:
            failure = ("invalid_request", None)
        raise OpenAIStructuredError(*failure)

    def _generate(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        if (
            type(request.max_output_tokens) is not int
            or not 1 <= request.max_output_tokens <= 100000
            or not isinstance(request.schema_name, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request.schema_name) is None
            or not isinstance(request.json_schema, dict)
            or request.json_schema.get("type") != "object"
            or not request.messages
            or len(request.messages) > 256
            or type(request.temperature) not in (int, float)
            or not math.isfinite(request.temperature)
            or not 0 <= request.temperature <= 2
        ):
            raise OpenAIStructuredError("invalid_request")
        for message in request.messages:
            if (
                set(message) != {"role", "content"}
                or message["role"] not in {"system", "developer", "user", "assistant"}
                or not isinstance(message["content"], str)
            ):
                raise OpenAIStructuredError("invalid_request")
        body = json.dumps(
            {
                "model": self.model,
                "input": request.messages,
                "max_output_tokens": request.max_output_tokens,
                "temperature": request.temperature,
                "store": False,
                "stream": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": request.schema_name,
                        "strict": True,
                        "schema": request.json_schema,
                    }
                },
            },
            allow_nan=False,
        ).encode()
        if len(body) > 2 * 1024 * 1024:
            raise OpenAIStructuredError("invalid_request")
        import httpx

        wire: bytes | None = None
        code = "transport_failure"
        try:
            started = time.monotonic()
            with httpx.Client(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(30, connect=5),
            ) as client:
                with client.stream(
                    "POST",
                    _ENDPOINT,
                    content=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code != 200:
                        code = "http_failure"
                    elif response.headers.get("content-encoding", "identity") != "identity":
                        code = "invalid_response"
                    else:
                        chunks = bytearray()
                        for chunk in response.iter_raw():
                            if len(chunks) + len(chunk) > self._max_response_bytes:
                                code = "response_too_large"
                                break
                            if time.monotonic() - started > 60:
                                code = "response_timeout"
                                break
                            chunks.extend(chunk)
                        else:
                            wire = bytes(chunks)
        except Exception:
            wire = None
        if wire is None:
            raise OpenAIStructuredError(code)
        usage: Usage | None = None
        code = "invalid_response"
        try:
            data = _json(wire)
            usage = self._usage(data)
            if (
                usage[1] > request.max_output_tokens
                or data.get("model") != self.model
                or data.get("status") != "completed"
                or data.get("error") is not None
                or data.get("incomplete_details") is not None
                or not isinstance(data.get("id"), str)
                or re.fullmatch(r"resp_[A-Za-z0-9_]{1,128}", data["id"]) is None
            ):
                raise ValueError("invalid response")
            contents = []
            for item in data["output"]:
                if item.get("type") == "reasoning":
                    continue
                if (
                    item.get("type") != "message"
                    or item.get("role") != "assistant"
                    or item.get("status") != "completed"
                ):
                    raise ValueError("unexpected output")
                contents.extend(item["content"])
            if len(contents) != 1:
                raise ValueError("ambiguous output")
            content = contents[0]
            refused = content.get("type") == "refusal"
            parsed = None
            if refused:
                if not isinstance(content.get("refusal"), str):
                    raise ValueError("invalid refusal")
            else:
                if content.get("type") != "output_text" or not isinstance(content.get("text"), str):
                    raise ValueError("invalid content")
                parsed = _json(content["text"])
                if not isinstance(parsed, dict):
                    raise ValueError("invalid structured object")
                code = "invalid_output"
                if self._validate(request.json_schema, parsed) is not None:
                    raise ValueError("validator must return None")
            return StructuredModelResult(
                provider="openai",
                model=self.model,
                response_id=data["id"],
                parsed=parsed,
                refused=refused,
                refusal="Provider refused the request" if refused else None,
                input_tokens=usage[0],
                output_tokens=usage[1],
                estimated_cost_usd=usage[3],
                raw={"status": "completed", "cached_input_tokens": usage[2]},
            )
        except Exception:
            failure = (code, usage)
        raise OpenAIStructuredError(*failure)
