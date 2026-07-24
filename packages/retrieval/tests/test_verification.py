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
    should_abstain,
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


def test_verifier_numeric_claim_without_evidence_numeric_is_non_supporting() -> None:
    """A claim that asserts a number cited to numeric-less evidence must not be
    graded entailed via lexical coverage alone (fail closed / non-supporting)."""
    v = MockCitationVerifier()
    # Full lexical coverage of the claim text — would be entailed if numeric were skipped.
    item = _item("a", "Revenue was 100 million dollars")
    edge = v.verify("Revenue was 100 million dollars", item, claim_numeric=_num("100"))
    assert edge.status == "irrelevant"
    assert edge.numeric_checks == {}
    assert "no numeric" in edge.rationale


def test_classify_claim_statuses() -> None:
    assert classify_claim(["entailed"]) == "supported"
    assert classify_claim(["entailed", "partial"]) == "partially_supported"
    assert classify_claim(["entailed", "contradictory"]) == "contradicted"
    assert classify_claim(["irrelevant"]) == "unsupported"
    assert classify_claim([]) == "unsupported"


def test_classify_claim_entailed_plus_irrelevant_is_partially_supported() -> None:
    """Load-bearing: an irrelevant companion must keep the claim from being
    waved through as fully ``supported`` (guards the all-edges-entailed check)."""
    assert classify_claim(["entailed", "irrelevant"]) == "partially_supported"


# --- verify_claims end to end ----------------------------------------------
def test_verify_claims_supported_and_numeric_checked() -> None:
    item = _item("a", "Revenue was 100", numeric=_num("100"))
    claim = GeneratedClaim(
        ord=0,
        text="Revenue was 100",
        status="unsupported",
        citations=(ClaimCitation(item_id="a", source_span_id="span-1"),),
        numeric=_num("100"),
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


# --- abstention (M2-022) ----------------------------------------------------
def _claim(status: str) -> GeneratedClaim:
    return GeneratedClaim(
        ord=0,
        text="x",
        status=status,
        citations=(ClaimCitation(item_id="a", source_span_id="s", status="entailed"),),
    )


def test_should_abstain_on_no_claims() -> None:
    assert should_abstain([]) is True


def test_should_abstain_when_all_unsupported() -> None:
    assert should_abstain([_claim("unsupported"), _claim("unsupported")]) is True


def test_no_abstain_when_any_support_or_contradiction() -> None:
    assert should_abstain([_claim("unsupported"), _claim("supported")]) is False
    # A contradicted claim is preserved and displayed, not abstained.
    assert should_abstain([_claim("contradicted")]) is False


def test_contradiction_preserves_all_spans() -> None:
    good = _item("a", "Revenue was 100", numeric=_num("100"))
    bad = _item("b", "Revenue was 100", span="span-2", numeric=_num("999"))
    claim = GeneratedClaim(
        ord=0,
        text="Revenue was 100",
        status="unsupported",
        citations=(
            ClaimCitation(item_id="a", source_span_id="span-1"),
            ClaimCitation(item_id="b", source_span_id="span-2"),
        ),
        numeric=_num("100"),
    )
    verified = verify_claims([claim], [good, bad], MockCitationVerifier())
    assert verified[0].status == "contradicted"
    # Both material spans are preserved on the contradicted claim.
    assert {c.item_id for c in verified[0].citations} == {"a", "b"}


def test_multi_citation_each_edge_checked_against_own_evidence() -> None:
    """A claim citing two different, individually-correct facts must not be
    contradicted: each edge is numeric-checked against its OWN cited evidence, not
    against the value of an arbitrary earlier citation."""
    a = _item("a", "revenue was reported", numeric=_num("100"))
    b = _item("b", "revenue was reported", span="span-2", numeric=_num("250"))
    claim = GeneratedClaim(
        ord=0,
        text="revenue was reported",
        status="unsupported",
        # Aggregate claim: it lists two operand facts and asserts no single scalar.
        citations=(
            ClaimCitation(item_id="a", source_span_id="span-1"),
            ClaimCitation(item_id="b", source_span_id="span-2"),
        ),
        calculation_lineage={"op": "sum", "operands": ["a", "b"]},
        numeric=None,
    )
    verified = verify_claims([claim], [a, b], MockCitationVerifier())
    assert verified[0].status != "contradicted"
    assert verified[0].status in {"supported", "derived"}
    assert all(c.status in {"entailed", "partial"} for c in verified[0].citations)


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
