"""Citation entailment, deterministic numeric checking and integrity (M2-021 / T0208).

Verification is the authority on every claim -> evidence edge. Generation
(M2-020) only *proposes* atomic claims; this module re-derives each edge from the
cited evidence so a claim's rendered status can never outrun what the evidence
supports:

* ``CitationVerifier`` is a typed ``Protocol``; ``MockCitationVerifier`` is the
  deterministic default (no network). Entailment is decided by lexical coverage
  of the claim by its evidence span, and — for arithmetic-bearing claims — by the
  numeric-tuple check, so a number that does not check out is *contradictory*
  regardless of how well the surrounding words overlap.
* ``validate_numeric`` checks value, unit, period, sign and scale as five
  orthogonal booleans using exact ``Decimal`` arithmetic (spec §11.4). ``value``
  compares magnitude and ``sign`` the polarity, so a sign flip is caught even
  when the magnitude matches.
* ``assert_citation_integrity`` fails closed *before* the database is touched:
  a citation to a non-accepted item is dangling, and a citation whose span does
  not belong to the accepted item is a cross-version reference. Both raise
  ``CitationIntegrityError`` (mirroring ``fel_guard_citation`` at the app layer).

``classify_claim`` folds an ordered claim's edges into the spec §11.3 closed
status set. Contradiction preservation and run-level abstention build on this in
M2-022.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from fel_retrieval.generation import (
    ClaimCitation,
    ContextItem,
    GeneratedClaim,
    NumericTuple,
)

# Lexical coverage thresholds for the mock entailment judgement. A claim whose
# tokens are fully covered by its evidence span is entailed; substantial-but-
# partial coverage is a partial edge; anything below is irrelevant.
_ENTAILED_COVERAGE = 1.0
_PARTIAL_COVERAGE = 0.5

# Numeric-check dimensions, in the fixed order they are reported (spec §11.4).
NUMERIC_CHECK_KEYS: tuple[str, ...] = ("value", "unit", "period", "sign", "scale")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class CitationIntegrityError(RuntimeError):
    """A citation is dangling or cross-version; the run must fail closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CitationEdge:
    """A verified claim -> evidence edge."""

    status: str
    numeric_checks: dict[str, bool]
    rationale: str


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _coverage(claim_text: str, evidence_text: str) -> float:
    """Fraction of the claim's tokens present in the evidence span."""
    claim_tokens = _tokens(claim_text)
    if not claim_tokens:
        return 0.0
    evidence_tokens = _tokens(evidence_text)
    covered = claim_tokens & evidence_tokens
    return len(covered) / len(claim_tokens)


def validate_numeric(claim: NumericTuple, evidence: NumericTuple) -> dict[str, bool]:
    """Check a claim's numeric tuple against its evidence, dimension by dimension.

    Five orthogonal booleans (spec §11.4): ``value`` (magnitude), ``unit``,
    ``period``, ``sign`` (polarity) and ``scale``. Magnitude and scale are
    compared exactly with ``Decimal`` so no float rounding can mask a mismatch.
    """
    return {
        "value": abs(claim.value) == abs(evidence.value),
        "unit": claim.unit == evidence.unit,
        "period": claim.period == evidence.period,
        "sign": claim.sign == evidence.sign,
        "scale": claim.scale == evidence.scale,
    }


class CitationVerifier(Protocol):
    """Classifies one claim -> evidence edge. ``name``/``model``/``version`` are
    recorded on every citation for provenance."""

    name: str
    model: str
    version: str

    def verify(
        self, claim_text: str, evidence: ContextItem, *, claim_numeric: NumericTuple | None
    ) -> CitationEdge: ...


class MockCitationVerifier:
    """Deterministic entailment + numeric verifier (no network).

    Text entailment is lexical coverage of the claim by its evidence span. When a
    numeric tuple is asserted, the numeric check is decisive: missing evidence
    numeric fails closed as non-supporting (never lexical ``entailed``), and any
    failed dimension makes the edge ``contradictory`` (the number is wrong).
    """

    name = "mock-entailment"
    model = "mock-verifier-v1"
    version = "v1"

    def verify(
        self, claim_text: str, evidence: ContextItem, *, claim_numeric: NumericTuple | None
    ) -> CitationEdge:
        numeric_checks: dict[str, bool] = {}
        if claim_numeric is not None:
            if evidence.numeric is None:
                # Claim asserts a number but the cited evidence has none — fail
                # closed as non-supporting; never grade entailed via lexical alone.
                return CitationEdge(
                    status="irrelevant",
                    numeric_checks={},
                    rationale="claim asserts numeric but evidence has no numeric tuple",
                )
            numeric_checks = validate_numeric(claim_numeric, evidence.numeric)
            if not all(numeric_checks.values()):
                failed = sorted(k for k, ok in numeric_checks.items() if not ok)
                return CitationEdge(
                    status="contradictory",
                    numeric_checks=numeric_checks,
                    rationale=f"numeric mismatch: {', '.join(failed)}",
                )

        coverage = _coverage(claim_text, evidence.text)
        if coverage >= _ENTAILED_COVERAGE:
            status = "entailed"
        elif coverage >= _PARTIAL_COVERAGE:
            status = "partial"
        else:
            status = "irrelevant"
        return CitationEdge(
            status=status,
            numeric_checks=numeric_checks,
            rationale=f"lexical coverage {coverage:.2f}",
        )


def assert_citation_integrity(
    citation: ClaimCitation, accepted: Mapping[str, ContextItem]
) -> ContextItem:
    """Fail closed on a dangling or cross-version citation; return the item.

    * Dangling: the cited item is not an accepted candidate of the run.
    * Cross-version: the citation's span is not the accepted item's own span
      (it references a different document version's span).
    """
    item = accepted.get(citation.item_id)
    if item is None:
        raise CitationIntegrityError(
            "DANGLING_CITATION",
            f"citation item {citation.item_id} is not an accepted candidate",
        )
    if citation.source_span_id != item.source_span_id:
        raise CitationIntegrityError(
            "CROSS_VERSION_CITATION",
            f"citation span {citation.source_span_id} does not belong to item {citation.item_id}",
        )
    return item


def classify_claim(edges: Sequence[str]) -> str:
    """Fold a claim's citation-edge statuses into a closed claim status (§11.3).

    * any ``contradictory`` edge -> ``contradicted`` (conflict is preserved);
    * all ``entailed`` (>=1) -> ``supported``;
    * any supporting edge with a non-entailed companion (``partial`` /
      ``irrelevant``) -> ``partially_supported``;
    * otherwise (no supporting edge) -> ``unsupported``.
    """
    if not edges:
        return "unsupported"
    if any(status == "contradictory" for status in edges):
        return "contradicted"
    if not any(status in {"entailed", "partial"} for status in edges):
        return "unsupported"
    if all(status == "entailed" for status in edges):
        return "supported"
    return "partially_supported"


def should_abstain(claims: Sequence[GeneratedClaim]) -> bool:
    """Whether the run must abstain for want of supporting evidence (M2-022).

    Missing evidence yields abstention: a run with no claims, or whose every
    claim is ``unsupported``, abstains. Contradictory evidence is *not*
    abstention — a ``contradicted`` claim is preserved and displayed (the run
    succeeds), so any claim that is supported/partially_supported/derived/
    contradicted keeps the run out of abstention.
    """
    if not claims:
        return True
    return all(claim.status == "unsupported" for claim in claims)


def verify_claims(
    claims: Sequence[GeneratedClaim],
    context: Sequence[ContextItem],
    verifier: CitationVerifier,
) -> tuple[GeneratedClaim, ...]:
    """Re-derive every claim's citation edges and support status from evidence.

    Raises ``CitationIntegrityError`` (fail closed) on any dangling/cross-version
    citation. A claim marked ``derived`` (calculation lineage present) that its
    evidence supports keeps the ``derived`` status.
    """
    accepted = {item.item_id: item for item in context}
    verified: list[GeneratedClaim] = []
    for claim in claims:
        new_citations: list[ClaimCitation] = []
        for citation in claim.citations:
            item = assert_citation_integrity(citation, accepted)
            # The claim asserts its own numeric; every edge checks that assertion
            # against its OWN cited evidence, so a second correctly-cited fact is
            # never mis-flagged by the value of an earlier one.
            edge = verifier.verify(claim.text, item, claim_numeric=claim.numeric)
            new_citations.append(
                ClaimCitation(
                    item_id=citation.item_id,
                    source_span_id=citation.source_span_id,
                    status=edge.status,
                    numeric_checks=edge.numeric_checks,
                    rationale=edge.rationale,
                    verifier=verifier.name,
                    model=verifier.model,
                    version=verifier.version,
                )
            )
        status = classify_claim([c.status for c in new_citations])
        if status == "supported" and claim.calculation_lineage:
            status = "derived"
        verified.append(
            GeneratedClaim(
                ord=claim.ord,
                text=claim.text,
                status=status,
                citations=tuple(new_citations),
                confidence=claim.confidence,
                calculation_lineage=claim.calculation_lineage,
                numeric=claim.numeric,
            )
        )
    return tuple(verified)


__all__ = [
    "NUMERIC_CHECK_KEYS",
    "CitationEdge",
    "CitationIntegrityError",
    "CitationVerifier",
    "MockCitationVerifier",
    "assert_citation_integrity",
    "classify_claim",
    "should_abstain",
    "validate_numeric",
    "verify_claims",
]
