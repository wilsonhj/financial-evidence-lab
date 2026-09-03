"""Constructor invariants and status types for the compiled-manifest shapes.

#137 item 4. The compiler refuses every one of these with a typed
``CompilationViolation`` and keeps doing so — that is the reviewer-facing path.
These tests pin the second line of defense: the shapes themselves refuse to
exist in an ungradeable state, for the callers the compiler does not front (a
manifest rebuilt from JSON, a fixture, a future grader). Nothing here changes
what a valid manifest serialises to; ``test_compile`` pins that byte for byte
against the committed manifest's checksum.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_retrieval.generation import CITATION_STATUSES, CLAIM_STATUSES
from fel_retrieval_evals.models import (
    ALLOWED_SCALE_EXPONENTS,
    RENDERED_CLAIM_STATUSES,
    SCALE_EXPONENTS,
    SUPPORTING_CITATION_STATUSES,
    CitationStatus,
    ClaimStatus,
    Evidence,
    GradedCitation,
    GradedClaim,
    Manifest,
    ManifestEntry,
    NumericAnswer,
    TextAnswer,
)


def _evidence(*, span_id: str | None = "span-1") -> Evidence:
    return Evidence(
        accession="0001628280-26-038798",
        form="10-Q",
        section="Financial Highlights",
        quote="Total revenue was $687.6 million.",
        evidence_id="ev-1",
        span_id=span_id,
    )


def _entry(**overrides: object) -> ManifestEntry:
    kwargs: dict[str, object] = {
        "id": "BM-0001",
        "category": "exact_fact_lookup",
        "issuer": {"ticker": "MDB"},
        "question": "What was revenue?",
        "as_of": "2026-05-28T12:00:00Z",
        "answerable": True,
        "expected_answer": TextAnswer(text="687.6"),
        "evidence": (_evidence(),),
        "documents_reviewed": ("0001628280-26-038798",),
    }
    kwargs.update(overrides)
    return ManifestEntry(**kwargs)  # type: ignore[arg-type]


# --- numeric answer: low <= high, scale in the closed set ------------------
def test_numeric_answer_accepts_a_point_and_a_range() -> None:
    point = NumericAnswer(Decimal("687.6"), Decimal("687.6"), "USD", 6, "Q1 FY2027")
    span = NumericAnswer(Decimal("680"), Decimal("690"), "USD", 6, "Q1 FY2027")
    assert point.low == point.high
    assert span.to_dict()["low"] == "680"


def test_numeric_answer_rejects_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="exceeds high"):
        NumericAnswer(Decimal("690"), Decimal("680"), "USD", 6, "Q1 FY2027")


def test_numeric_answer_rejects_a_scale_outside_the_closed_set() -> None:
    """A magnitude off by three orders is invisible in the rendered answer."""
    with pytest.raises(ValueError, match="scale exponent 4"):
        NumericAnswer(Decimal("1"), Decimal("1"), "USD", 4, "Q1 FY2027")


def test_allowed_exponents_are_derived_from_the_scale_words() -> None:
    assert ALLOWED_SCALE_EXPONENTS == frozenset(SCALE_EXPONENTS.values())
    for exponent in ALLOWED_SCALE_EXPONENTS:
        NumericAnswer(Decimal("1"), Decimal("1"), "USD", exponent, "Q1 FY2027")


# --- manifest entry: the answerable flag must match what it carries --------
def test_answerable_entry_needs_an_expected_answer_and_evidence() -> None:
    with pytest.raises(ValueError, match="needs an expected_answer"):
        _entry(expected_answer=None)
    with pytest.raises(ValueError, match="must cite evidence"):
        _entry(evidence=())


def test_negative_case_must_stay_a_negative_case() -> None:
    negative = _entry(answerable=False, expected_answer=None, evidence=())
    assert negative.answerable is False
    with pytest.raises(ValueError, match="no expected_answer"):
        _entry(answerable=False, evidence=())
    with pytest.raises(ValueError, match="cite no evidence"):
        _entry(answerable=False, expected_answer=None)
    with pytest.raises(ValueError, match="documents_reviewed"):
        _entry(answerable=False, expected_answer=None, evidence=(), documents_reviewed=())


# --- manifest: "resolved" is a claim about provenance ----------------------
def test_resolved_manifest_may_not_carry_an_unresolved_anchor() -> None:
    with pytest.raises(ValueError, match="unresolved evidence"):
        Manifest(
            corpus_version_id="cv-1",
            resolved=True,
            entries=(_entry(evidence=(_evidence(span_id=None),)),),
        )


def test_unresolved_manifest_accepts_span_less_evidence() -> None:
    manifest = Manifest(
        corpus_version_id=None,
        resolved=False,
        entries=(_entry(evidence=(_evidence(span_id=None),)),),
    )
    assert manifest.body()["resolved"] is False


# --- claim / citation status types -----------------------------------------
def test_status_sets_match_the_generation_contract() -> None:
    """The eval side grades what generation emits; the two closed sets are one."""
    assert {status.value for status in ClaimStatus} == set(CLAIM_STATUSES)
    assert {status.value for status in CitationStatus} == set(CITATION_STATUSES)


def test_statuses_are_strings_end_to_end() -> None:
    claim = GradedClaim(text="Revenue was $687.6 million.", status="supported")
    assert claim.status == "supported"
    assert claim.status is ClaimStatus.SUPPORTED
    assert claim.to_dict()["status"] == "supported"


def test_unknown_status_is_refused_at_the_boundary() -> None:
    with pytest.raises(ValueError):
        GradedClaim(text="x", status="probably_fine")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GradedCitation(evidence_id="ev-1", status="looks_right")  # type: ignore[arg-type]


def test_derived_claim_requires_its_lineage() -> None:
    """``derived`` asserts the number was CALCULATED; without lineage it renders
    as an unqualified conclusion with no record of how it was reached."""
    with pytest.raises(ValueError, match="calculation_lineage"):
        GradedClaim(text="Gross margin was 71%.", status=ClaimStatus.DERIVED)
    claim = GradedClaim(
        text="Gross margin was 71%.",
        status=ClaimStatus.DERIVED,
        calculation_lineage={"op": "divide", "operands": ["gross_profit", "revenue"]},
    )
    assert claim.rendered is True


def test_only_supported_and_derived_claims_render() -> None:
    assert RENDERED_CLAIM_STATUSES == {ClaimStatus.SUPPORTED, ClaimStatus.DERIVED}
    for status in ClaimStatus:
        claim = GradedClaim(
            text="x",
            status=status,
            calculation_lineage={"op": "sum"} if status is ClaimStatus.DERIVED else None,
        )
        assert claim.rendered is (status in RENDERED_CLAIM_STATUSES)


def test_supporting_citation_statuses() -> None:
    assert SUPPORTING_CITATION_STATUSES == {CitationStatus.ENTAILED, CitationStatus.PARTIAL}
    for status in CitationStatus:
        citation = GradedCitation(evidence_id="ev-1", status=status)
        assert citation.supporting is (status in SUPPORTING_CITATION_STATUSES)
        assert citation.to_dict()["status"] == status.value
