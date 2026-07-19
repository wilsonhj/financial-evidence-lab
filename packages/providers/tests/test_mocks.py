"""Provider mocks are deterministic, bounded, and fail closed correctly."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from fel_providers import (
    MockEmbeddingProvider,
    MockFredClient,
    MockLLMProvider,
    MockMarketDataProvider,
    MockSecClient,
    MockStorageProvider,
    MockStructuredLLMProvider,
    StructuredGenerationRequest,
)


def test_llm_deterministic() -> None:
    provider = MockLLMProvider()
    assert provider.generate("q", max_tokens=8) == provider.generate("q", max_tokens=8)


def test_embeddings_dimension_cap_and_unit_norm() -> None:
    with pytest.raises(ValueError):
        MockEmbeddingProvider(dimensions=1536)
    provider = MockEmbeddingProvider(dimensions=256)
    [vec] = provider.embed(["revenue"])
    assert len(vec) == 256
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-9


def test_storage_immutable() -> None:
    storage = MockStorageProvider()
    storage.put("a", b"1")
    with pytest.raises(ValueError):
        storage.put("a", b"2")
    assert storage.get("a") == b"1"
    assert "sig=" in storage.signed_url("a", expires_seconds=60)


def test_market_data_decimal_and_fail_closed() -> None:
    provider = MockMarketDataProvider()
    bars = provider.daily_adjusted("CRM", start=date(2026, 1, 5), end=date(2026, 1, 9))
    assert len(bars) == 5
    assert isinstance(bars[0].adjusted_close, Decimal)
    with pytest.raises(ValueError):
        provider.daily_adjusted("NOADJ", start=date(2026, 1, 5), end=date(2026, 1, 9))


def test_sec_and_fred_mock_shapes() -> None:
    assert MockSecClient().submissions("0001108524")["mock"] is True
    points = MockFredClient().series_vintage("GDP", as_of=datetime(2026, 7, 1))
    assert len(points) == 4 and isinstance(points[0][1], Decimal)


def _structured_request(*, content: str = "extract kpi") -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        schema_name="extraction-payload",
        schema_version="v1",
        json_schema={"type": "object", "properties": {"kind": {"const": "kpi"}}},
        messages=[{"role": "user", "content": content}],
        max_output_tokens=64,
    )


def test_structured_llm_deterministic_and_records_metadata() -> None:
    provider = MockStructuredLLMProvider()
    first = provider.generate_structured(_structured_request())
    second = provider.generate_structured(_structured_request())
    assert first == second
    assert first.provider == "mock"
    assert first.model == "mock-structured-v1"
    assert first.response_id.startswith("mockresp_")
    assert first.refused is False
    assert first.refusal is None
    assert first.parsed is not None
    assert first.parsed["mock"] is True
    assert first.input_tokens >= 1
    assert first.output_tokens >= 1
    assert first.estimated_cost_usd == Decimal("0")
    assert first.raw["digest"]


def test_structured_llm_refusal_path() -> None:
    provider = MockStructuredLLMProvider()
    result = provider.generate_structured(_structured_request(content="REFUSE this"))
    assert result.refused is True
    assert result.parsed is None
    assert result.refusal is not None and result.refusal.startswith("mock-refusal:")
