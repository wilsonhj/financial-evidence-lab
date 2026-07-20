"""Unit tests for citation verification, numeric checks and integrity (M2-021)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_retrieval.generation import ClaimCitation, ContextItem, GeneratedClaim, NumericTuple
from fel_retrieval.verification import (
    CitationIntegrityError,
    MockCitationVerifier,
    assert_citation_integrity,
    classify_claim,
    validate_numeric,
    verify_claims,
)


def _num(value: str, unit: str = "USD", period: str = "FY2025", scale: int = 6) -> NumericTuple:
    return NumericTuple(value=Decimal(value), unit=unit, period=period, scale=scale)


def _item(
    item_id: str,
    text: str,
    *,
    span: str = "span-1",
    dv: str = "dv-1",
    numeric: NumericTuple | None = None,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        kind="fact" if numeric else "passage",
        text=text,
        source_span_id=span,
        document_version_id=dv,
        financial_fact_id="ff-1" if numeric else None,
        numeric=numeric,
    )


# --- numeric validator (value/unit/period/sign/scale) ----------------------
def test_numeric_all_pass() -> None:
    checks = validate_numeric(_num("100"), _num("100"))
    assert checks == {"value": True, "unit": True, "period": True, "sign": True, "scale": True}


def test_numeric_value_magnitude_mismatch() -> None:
    checks = validate_numeric(_num("100"), _num("101"))
    assert checks["value"] is False
    assert checks["unit"] and checks["period"] and checks["scale"]


def test_numeric_sign_mismatch_independent_of_magnitude() -> None:
    checks = validate_numeric(_num("-100"), _num("100"))
    assert checks["value"] is True  # magnitude matches
    assert checks["sign"] is False  # polarity differs


def test_numeric_unit_period_scale_mismatch() -> None:
    assert validate_numeric(_num("100", unit="EUR"), _num("100"))["unit"] is False
    assert validate_numeric(_num("100", period="FY2024"), _num("100"))["period"] is False
    assert validate_numeric(_num("100", scale=3), _num("100"))["scale"] is False


def test_numeric_uses_exact_decimal() -> None:
    # 0.1 + 0.2 exact under Decimal; float would drift.
    claim = _num("0.3")
    evidence = NumericTuple(Decimal("0.1") + Decimal("0.2"), "USD", "FY2025", 6)
    assert validate_numeric(claim, evidence)["value"] is True


# --- integrity (dangling / cross-version) ----------------------------------
def test_dangling_citation_fails_closed() -> None:
    accepted = {"a": _item("a", "x")}
    citation = ClaimCitation(item_id="missing", source_span_id="span-1")
    with pytest.raises(CitationIntegrityError) as exc:
        assert_citation_integrity(citation, accepted)
    assert exc.value.code == "DANGLING_CITATION"


def test_cross_version_span_fails_closed() -> None:
    accepted = {"a": _item("a", "x", span="span-1")}
    citation = ClaimCitation(item_id="a", source_span_id="span-OTHER")
    with pytest.raises(CitationIntegrityError) as exc:
        assert_citation_integrity(citation, accepted)
    assert exc.value.code == "CROSS_VERSION_CITATION"


# --- entailment classification ---------------------------------------------
def test_verifier_entailed_on_full_coverage() -> None:
    v = MockCitationVerifier()
    item = _item("a", "Revenue was 100 million dollars")
    edge = v.verify("Revenue was 100 million", item, claim_numeric=None)
    assert edge.status == "entailed"


def test_verifier_irrelevant_on_low_coverage() -> None:
    v = MockCitationVerifier()
    item = _item("a", "Weather is sunny today")
    edge = v.verify("Revenue grew sharply worldwide", item, claim_numeric=None)
    assert edge.status == "irrelevant"


def test_verifier_numeric_mismatch_is_contradictory() -> None:
    v = MockCitationVerifier()
    item = _item("a", "Revenue was 100", numeric=_num("100"))
    edge = v.verify("Revenue was 999", item, claim_numeric=_num("999"))
    assert edge.status == "contradictory"
    assert edge.numeric_checks["value"] is False


def test_classify_claim_statuses() -> None:
    assert classify_claim(["entailed"]) == "supported"
    assert classify_claim(["entailed", "partial"]) == "partially_supported"
    assert classify_claim(["entailed", "contradictory"]) == "contradicted"
    assert classify_claim(["irrelevant"]) == "unsupported"
    assert classify_claim([]) == "unsupported"


# --- verify_claims end to end ----------------------------------------------
def test_verify_claims_supported_and_numeric_checked() -> None:
    item = _item("a", "Revenue was 100", numeric=_num("100"))
    claim = GeneratedClaim(
        ord=0,
        text="Revenue was 100",
        status="unsupported",
        citations=(ClaimCitation(item_id="a", source_span_id="span-1"),),
    )
    verified = verify_claims([claim], [item], MockCitationVerifier())
    assert verified[0].status == "supported"
    citation = verified[0].citations[0]
    assert citation.status == "entailed"
    assert citation.verifier == "mock-entailment"
    assert all(citation.numeric_checks.values())


def test_verify_claims_derived_preserved() -> None:
    item = _item("a", "Gross margin was 60 percent")
    claim = GeneratedClaim(
        ord=0,
        text="Gross margin was 60 percent",
        status="unsupported",
        citations=(ClaimCitation(item_id="a", source_span_id="span-1"),),
        calculation_lineage={"op": "divide", "operands": ["revenue", "cost"]},
    )
    verified = verify_claims([claim], [item], MockCitationVerifier())
    assert verified[0].status == "derived"


def test_verify_claims_dangling_raises() -> None:
    item = _item("a", "x")
    claim = GeneratedClaim(
        ord=0,
        text="x",
        status="unsupported",
        citations=(ClaimCitation(item_id="ghost", source_span_id="span-1"),),
    )
    with pytest.raises(CitationIntegrityError):
        verify_claims([claim], [item], MockCitationVerifier())
