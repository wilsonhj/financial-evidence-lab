"""Explicit-key OpenAI embedding transport; no runtime registration or secret lookup."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

_ENDPOINT = "https://api.openai.com/v1/embeddings"
_MODELS = frozenset({"text-embedding-3-small", "text-embedding-3-large"})


@dataclass(frozen=True)
class EmbeddingUsage:
    """Safe per-attempt metadata. None means unknown, never free usage."""

    model: str
    input_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: Decimal | None
    status_code: int | None
    provider: str = "openai"


class OpenAIEmbeddingError(RuntimeError):
    """Static diagnostics only; known billable usage survives invalid results."""

    def __init__(self, code: str, usage: EmbeddingUsage | None = None) -> None:
        super().__init__(f"OpenAI embedding request failed: {code}")
        self.code = code
        self.usage = usage


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("nonfinite JSON number")


class OpenAIEmbeddingProvider:
    """512-dimension provider; caller owns credential authorization and accounting.

    Sink is called once per attempted request, before returning vectors or raising
    for malformed/failed responses. A failing sink aborts and preserves metadata
    on the safe exception; callers must reconcile, not blindly retry the call.
    """

    dimensions = 512

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        price_per_million_tokens: Decimal,
        usage_sink: Callable[[EmbeddingUsage], None],
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if (
            not isinstance(api_key, str)
            or not 1 <= len(api_key) <= 512
            or any(not 33 <= ord(c) <= 126 for c in api_key)
            or not isinstance(model, str)
            or model not in _MODELS
            or not isinstance(price_per_million_tokens, Decimal)
            or not price_per_million_tokens.is_finite()
            or not Decimal(0) <= price_per_million_tokens <= Decimal(1000)
            or not -12 <= int(price_per_million_tokens.as_tuple().exponent) <= 3
            or not callable(usage_sink)
            or type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
            or type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 4_000_000
        ):
            raise OpenAIEmbeddingError("invalid_configuration")
        self._api_key = api_key
        self.model = model
        self._price = price_per_million_tokens
        self._sink = usage_sink
        self._transport = transport
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def embed(self, texts: list[str]) -> list[list[float]]:
        if type(texts) is not list or len(texts) > 64:
            raise OpenAIEmbeddingError("invalid_input")
        if not texts:
            return []
        valid = True
        payload = b""
        try:
            sizes = [len(text.encode("utf-8")) for text in texts if type(text) is str]
            valid = (
                len(sizes) == len(texts)
                and all(0 < size <= 8192 for size in sizes)
                and sum(sizes) <= 128_000
            )
            if valid:
                payload = json.dumps(
                    {
                        "input": texts,
                        "model": self.model,
                        "dimensions": 512,
                        "encoding_format": "float",
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
        except (UnicodeError, ValueError):
            valid = False
        if not valid or len(payload) > 256_000:
            raise OpenAIEmbeddingError("invalid_input")

        # Imported only when a request is actually made; frozen protocols need no httpx.
        import httpx

        code: str | None = None
        status: int | None = None
        body = bytearray()
        try:
            started = time.monotonic()
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "POST",
                    _ENDPOINT,
                    content=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    status = response.status_code
                    if status != 200:
                        code = "http_error"
                    elif response.headers.get("content-encoding", "identity") != "identity":
                        code = "invalid_encoding"
                    else:
                        chunks = (
                            (response.content,)
                            if response.is_stream_consumed
                            else response.iter_raw()
                        )
                        for chunk in chunks:
                            if time.monotonic() - started > 60:
                                code = "deadline_exceeded"
                                break
                            if len(body) + len(chunk) > self._max_response_bytes:
                                code = "response_too_large"
                                break
                            body.extend(chunk)
        except Exception:
            # Transport diagnostics may contain Authorization, input or upstream body.
            code = "transport_error"
        usage = EmbeddingUsage(self.model, None, None, None, status)
        data: Any = None
        if code is None:
            try:
                data = json.loads(body, object_pairs_hook=_pairs, parse_constant=_constant)
                raw_usage = data.get("usage") if isinstance(data, dict) else None
                if not isinstance(raw_usage, dict):
                    raise ValueError("invalid usage")
                prompt = raw_usage.get("prompt_tokens")
                total = raw_usage.get("total_tokens")
                if type(prompt) is not int or not 0 < prompt <= 300_000 or total != prompt:
                    raise ValueError("invalid usage")
                if type(total) is not int:
                    raise ValueError("invalid usage")
                with localcontext() as ctx:
                    ctx.prec = 50
                    cost = Decimal(prompt) * self._price / Decimal(1_000_000)
                usage = EmbeddingUsage(self.model, prompt, total, cost, status)
            except Exception:
                code = "invalid_response"
        sink_failed = False
        try:
            self._sink(usage)
        except Exception:
            sink_failed = True
        # Raise outside handlers: even __context__ contains no hostile diagnostics.
        if sink_failed:
            raise OpenAIEmbeddingError("usage_sink_failed", usage)
        if code is not None:
            raise OpenAIEmbeddingError(code, usage)
        vectors: list[list[float]] = []
        invalid = False
        try:
            if data.get("model") != self.model or data.get("object") != "list":
                raise ValueError("invalid identity")
            rows = data.get("data")
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError("invalid batch")
            indexed: dict[int, list[float]] = {}
            for row in rows:
                if not isinstance(row, dict) or row.get("object") != "embedding":
                    raise ValueError("invalid row")
                index = row.get("index")
                vector = row.get("embedding")
                if type(index) is not int or not 0 <= index < len(texts) or index in indexed:
                    raise ValueError("invalid index")
                if not isinstance(vector, list) or len(vector) != self.dimensions:
                    raise ValueError("invalid dimensions")
                if any(type(n) not in (int, float) or not math.isfinite(n) for n in vector):
                    raise ValueError("invalid vector")
                if not any(n != 0 for n in vector):
                    raise ValueError("zero vector")
                indexed[index] = [float(n) for n in vector]
            vectors = [indexed[i] for i in range(len(texts))]
        except Exception:
            invalid = True
        if invalid:
            raise OpenAIEmbeddingError("invalid_response", usage)
        return vectors
