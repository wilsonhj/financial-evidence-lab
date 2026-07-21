"""Unit tests for structured claim generation (M2-020 / T0207)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_retrieval.generation import (
    CLAIM_STATUSES,
    ClaimCitation,
    ContextItem,
    GeneratedClaim,
    NumericTuple,
    StructuredClaimGenerator,
)


def _ctx(item_id: str, text: str, *, span: str = "span-1") -> ContextItem:
    return ContextItem(
        item_id=item_id,
        kind="passage",
        text=text,
        source_span_id=span,
        document_version_id="dv-1",
    )


def test_generates_one_atomic_supported_claim_per_context_item() -> None:
    gen = StructuredClaimGenerator(MockStructuredLLMProvider())
    context = [
        _ctx("11111111-1111-4111-8111-111111111111", "Revenue was $100 million."),
        _ctx("22222222-2222-4222-8222-222222222222", "Net income was $28 million."),
    ]
    result = gen.generate("What was revenue?", context, as_of="2026-01-01T00:00:00+00:00")

    assert not result.refused
    assert result.provider == "mock"
    assert len(result.claims) == 2
    assert [c.ord for c in result.claims] == [0, 1]
    for claim, item in zip(result.claims, context, strict=True):
        assert claim.text == item.text
        assert claim.status == "supported"
        assert claim.status in CLAIM_STATUSES
        assert len(claim.citations) == 1
        assert claim.citations[0].item_id == item.item_id
        assert claim.citations[0].source_span_id == item.source_span_id
        assert claim.citations[0].status == "entailed"
        assert claim.confidence == Decimal("1")


def test_refusal_yields_no_claims_and_records_usage() -> None:
    gen = StructuredClaimGenerator(MockStructuredLLMProvider())
    # The mock provider refuses when any message contains "REFUSE".
    result = gen.generate("REFUSE to answer", [_ctx("id", "x")], as_of="2026-01-01T00:00:00+00:00")
    assert result.refused
    assert result.refusal is not None
    assert result.claims == ()
    assert result.output_tokens >= 1


def test_empty_context_yields_no_claims() -> None:
    gen = StructuredClaimGenerator(MockStructuredLLMProvider())
    result = gen.generate("q", [], as_of="2026-01-01T00:00:00+00:00")
    assert not result.refused
    assert result.claims == ()


def test_illegal_claim_status_rejected() -> None:
    with pytest.raises(ValueError, match="illegal claim status"):
        GeneratedClaim(ord=0, text="x", status="bogus", citations=())


def test_illegal_citation_status_rejected() -> None:
    with pytest.raises(ValueError, match="illegal citation status"):
        GeneratedClaim(
            ord=0,
            text="x",
            status="supported",
            citations=(ClaimCitation(item_id="i", source_span_id="s", status="bogus"),),
        )


def test_numeric_tuple_sign_is_derived() -> None:
    assert NumericTuple(Decimal("1.5"), "USD", "FY2025", 6).sign == 1
    assert NumericTuple(Decimal("-1.5"), "USD", "FY2025", 6).sign == -1
    assert NumericTuple(Decimal("0"), "USD", "FY2025", 6).sign == 0
