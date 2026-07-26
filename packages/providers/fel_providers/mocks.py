"""Deterministic mock providers: same input -> same output, no network, no
credentials. These are the default bindings for all M0/M1 development."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fel_providers.interfaces import (
    MarketBar,
    StructuredGenerationRequest,
    StructuredModelResult,
)


class MockLLMProvider:
    def generate(self, prompt: str, *, max_tokens: int) -> str:
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        return f"[mock-completion {digest} max_tokens={max_tokens}]"


# Extraction role schema names (worker-local RoleSpec.schema_name values).
# When matched, the mock returns schema-valid envelopes for M3 workflows.
_EXTRACTION_ROLE_SCHEMAS = frozenset(
    {
        "classifier",
        "candidates",
        "kpi",
        "guidance",
        "revenue_driver",
        # Aliases kept for any callers still using the longer names.
        "extraction-classifier",
        "extraction-fact-table",
        "extraction-step-output",
    }
)

_FIXTURE_ENTITY = "11111111-1111-4111-8111-111111111111"
_FIXTURE_SPAN = "22222222-2222-4222-8222-222222222222"


def _load_extraction_payload_fixtures() -> dict[str, Any]:
    """Load contract fixtures when present; fall back to inline KPI/guidance/driver."""
    candidates = [
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "fixtures"
        / "extraction-payloads.valid.json",
        Path(__file__).resolve().parents[4]
        / "packages"
        / "contracts"
        / "fixtures"
        / "extraction-payloads.valid.json",
    ]
    for path in candidates:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
    return {
        "kpi": {
            "schema_version": "extraction-payload/v1",
            "kind": "kpi",
            "entity_id": _FIXTURE_ENTITY,
            "issuer_label": "Example SaaS",
            "metric_id": "arr",
            "raw_value": "$100 million",
            "value": "100",
            "unit": "USD",
            "currency": "USD",
            "scale": 6,
            "sign": "positive",
            "period": {"type": "instant", "instant": "2026-06-30", "fiscal_period": "FY2026-Q2"},
            "dimensions": {},
            "definition": "Annual recurring revenue",
            "qualifiers": {"currency": "USD", "construction": "ARR"},
            "reported_or_derived": "reported",
        },
        "guidance_point": {
            "schema_version": "extraction-payload/v1",
            "kind": "guidance",
            "entity_id": _FIXTURE_ENTITY,
            "issuer_label": "Example SaaS",
            "metric_id": "revenue",
            "raw_value": "approximately $120 million",
            "shape": "point",
            "value": "120",
            "unit": "USD",
            "currency": "USD",
            "scale": 6,
            "sign": "positive",
            "period": {"type": "forecast", "end": "2026-09-30", "fiscal_period": "FY2026-Q3"},
            "dimensions": {},
            "definition": None,
            "qualifiers": {},
            "reported_or_derived": "management_assertion",
        },
        "revenue_driver": {
            "schema_version": "extraction-payload/v1",
            "kind": "revenue_driver",
            "entity_id": _FIXTURE_ENTITY,
            "issuer_label": "Example SaaS",
            "metric_id": "price",
            "raw_value": "pricing contributed to growth",
            "category": "price",
            "description": "Pricing contributed to revenue growth.",
            "direction": "positive",
            "target_metric_ids": ["revenue"],
            "period": {
                "type": "duration",
                "start": "2026-04-01",
                "end": "2026-06-30",
                "fiscal_period": "FY2026-Q2",
            },
            "dimensions": {},
            "definition": None,
            "qualifiers": {},
            "reported_or_derived": "management_assertion",
        },
    }


def _extraction_envelope_for(request: StructuredGenerationRequest) -> dict[str, object]:
    """Return a schema-valid parsed object for extraction role schemas."""
    if any("ABSTAIN" in (m.get("content") or "") for m in request.messages):
        if request.schema_name in {"classifier", "extraction-classifier"}:
            return {
                "document_type": "unknown",
                "sections": [],
                "relevant_modes": [],
            }
        if request.schema_name in {"candidates", "extraction-fact-table"}:
            return {"candidates": []}
        return {"proposals": []}

    if request.schema_name in {"classifier", "extraction-classifier"}:
        return {
            "document_type": "10-Q",
            "sections": [{"source_span_id": _FIXTURE_SPAN, "label": "md&a"}],
            "relevant_modes": ["kpi", "guidance", "revenue_driver"],
        }
    if request.schema_name in {"candidates", "extraction-fact-table"}:
        return {
            "candidates": [
                {
                    "source_span_id": _FIXTURE_SPAN,
                    "metric_hint": "arr",
                    "raw_value": "$100 million",
                    "table_role": "kpi_row",
                }
            ]
        }

    fixtures = _load_extraction_payload_fixtures()
    if request.schema_name == "guidance":
        item_raw = fixtures["guidance_point"]
        if not isinstance(item_raw, dict):
            raise TypeError("guidance_point fixture must be an object")
        item = dict(item_raw)
        item["evidence"] = [{"source_span_id": _FIXTURE_SPAN, "role": "supports"}]
        return {"proposals": [item], "notes": None}
    if request.schema_name == "revenue_driver":
        item_raw = fixtures["revenue_driver"]
        if not isinstance(item_raw, dict):
            raise TypeError("revenue_driver fixture must be an object")
        item = dict(item_raw)
        item["evidence"] = [{"source_span_id": _FIXTURE_SPAN, "role": "supports"}]
        return {"proposals": [item], "notes": None}
    # kpi / extraction-step-output default — enrich qualifiers for ontology gates
    kpi_raw = fixtures["kpi"]
    if not isinstance(kpi_raw, dict):
        raise TypeError("kpi fixture must be an object")
    kpi = dict(kpi_raw)
    quals_raw = kpi.get("qualifiers") or {}
    quals = dict(quals_raw) if isinstance(quals_raw, dict) else {}
    quals.setdefault("currency", "USD")
    quals.setdefault("construction", "reported_arr")
    quals.setdefault("scope", "consolidated")
    kpi["qualifiers"] = quals
    kpi["evidence"] = [{"source_span_id": _FIXTURE_SPAN, "role": "supports"}]
    return {"proposals": [kpi], "notes": None}


class MockStructuredLLMProvider:
    """Deterministic structured mock: same request -> same result, no network.

    For M3 extraction role ``schema_name`` values, returns schema-valid envelopes
    shaped like worker-local classifier/fact-table schemas or contract
    ``extraction-payload`` items inside ``proposals[]``. Protocol shape unchanged.
    """

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
        elif request.schema_name in _EXTRACTION_ROLE_SCHEMAS:
            parsed = _extraction_envelope_for(request)
            refusal = None
            output_tokens = min(request.max_output_tokens, 128)
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
