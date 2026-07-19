"""Deterministic mock providers: same input -> same output, no network, no
credentials. These are the default bindings for all M0/M1 development."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from fel_providers.interfaces import (
    MarketBar,
    StructuredGenerationRequest,
    StructuredModelResult,
)


class MockLLMProvider:
    def generate(self, prompt: str, *, max_tokens: int) -> str:
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        return f"[mock-completion {digest} max_tokens={max_tokens}]"


class MockStructuredLLMProvider:
    """Deterministic structured mock: same request -> same result, no network."""

    provider = "mock"
    model = "mock-structured-v1"

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        if request.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be >= 1")
        seed_material = "|".join(
            [
                request.schema_name,
                request.schema_version,
                json.dumps(request.json_schema, sort_keys=True, default=str),
                json.dumps(request.messages, sort_keys=True),
                str(request.max_output_tokens),
                str(request.temperature),
            ]
        )
        digest = hashlib.sha256(seed_material.encode()).hexdigest()
        refused = any("REFUSE" in (message.get("content") or "") for message in request.messages)
        input_tokens = max(1, len(seed_material) // 4)
        output_tokens = 8 if refused else min(request.max_output_tokens, 32)
        parsed: dict[str, object] | None
        refusal: str | None
        if refused:
            parsed = None
            refusal = f"mock-refusal:{digest[:12]}"
        else:
            parsed = {
                "schema_name": request.schema_name,
                "schema_version": request.schema_version,
                "mock": True,
                "digest": digest[:24],
            }
            refusal = None
        return StructuredModelResult(
            provider=self.provider,
            model=self.model,
            response_id=f"mockresp_{digest[:16]}",
            parsed=parsed,
            refused=refused,
            refusal=refusal,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=Decimal("0"),
            raw={
                "provider": self.provider,
                "model": self.model,
                "digest": digest,
                "refused": refused,
            },
        )


class MockEmbeddingProvider:
    """Hash-seeded unit vectors; dimensions match the ADR-0002 <=512 mandate."""

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions > 512:
            raise ValueError("ADR-0002 caps embedding dimensions at 512")
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode()).digest()
            raw = [(seed[i % len(seed)] - 128) / 128.0 + 1e-9 for i in range(self.dimensions)]
            norm = math.sqrt(sum(v * v for v in raw))
            vectors.append([v / norm for v in raw])
        return vectors


class MockStorageProvider:
    """In-memory immutable store; puts of a new value to an existing key fail."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        if key in self._blobs and self._blobs[key] != data:
            raise ValueError(f"immutable key already exists: {key}")
        self._blobs[key] = data
        return f"mock://{key}"

    def get(self, key: str) -> bytes:
        return self._blobs[key]

    def signed_url(self, key: str, *, expires_seconds: int) -> str:
        token = hashlib.sha256(f"{key}:{expires_seconds}".encode()).hexdigest()[:16]
        return f"mock://{key}?sig={token}&exp={expires_seconds}"


class MockMarketDataProvider:
    """Deterministic adjusted bars; fails closed for the sentinel ticker
    NOADJ to exercise the FOR-005 missing-adjustment path."""

    def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]:
        if ticker == "NOADJ":
            raise ValueError("corporate-action adjustments unavailable (fail closed)")
        seed = int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)
        bars: list[MarketBar] = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                drift = (seed % 97) + (day.toordinal() % 13)
                bars.append(
                    MarketBar(
                        day=day,
                        adjusted_close=Decimal("100") + Decimal(drift) / 10,
                        volume=1_000_000 + (seed + day.toordinal()) % 50_000,
                        dividend=Decimal("0"),
                        split_factor=Decimal("1"),
                    )
                )
            day += timedelta(days=1)
        return bars


class MockSecClient:
    def submissions(self, cik: str) -> dict[str, object]:
        return {
            "cik": cik,
            "filings": {"recent": {"accessionNumber": [], "form": [], "filingDate": []}},
            "mock": True,
        }

    def fetch_document(self, url: str) -> bytes:
        return f"<html><!-- mock document for {url} --></html>".encode()


class MockFredClient:
    def series_vintage(self, series_id: str, *, as_of: datetime) -> list[tuple[date, Decimal]]:
        anchor = date(as_of.year, as_of.month, 1)
        seed = int(hashlib.sha256(series_id.encode()).hexdigest()[:6], 16)
        return [
            (anchor - timedelta(days=30 * i), Decimal(seed % 500) / 10 + Decimal(i))
            for i in range(4)
        ]
