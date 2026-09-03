"""Typed seed records and compiled-manifest shapes (M2-023 / T0214a).

The raw seed (``evals/datasets/benchmark-seed/questions.jsonl``, reconciled from
PR #74) is untyped JSONL. These dataclasses give the compiler a checked view of
one record and of the checksum-pinned manifest it emits. All arithmetic-bearing
fields are exact ``Decimal`` strings end-to-end (house rule); ranges normalise to
an inclusive ``[low, high]`` (a point answer has ``low == high``).

Every shape here also enforces its own invariants in ``__post_init__`` (#137
item 4). The compiler already refuses each of these with a typed
``CompilationViolation``, and that stays the reviewer-facing path; the
constructor guard is the second line of defense, for the callers the compiler
does not front — a manifest rebuilt from JSON, a test fixture, a future grader.
An unenforced invariant is a comment, and a comment cannot fail a build. The
guards are structural only, so nothing they accept or reject changes the JSON a
valid manifest serialises to.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

# Human scale words -> base-ten exponent. The pinned closed set; an unknown scale
# fails compilation (a silently-wrong magnitude is the exact bug this guards).
SCALE_EXPONENTS: dict[str, int] = {"ones": 0, "thousands": 3, "millions": 6, "billions": 9}

# The exponents a normalised answer may carry, derived from the closed scale set
# above so the two can never drift apart.
ALLOWED_SCALE_EXPONENTS: frozenset[int] = frozenset(SCALE_EXPONENTS.values())

MANIFEST_SCHEMA_VERSION = "m2-smoke-manifest/v1"


class CitationStatus(StrEnum):
    """Closed citation-edge status set (spec §11), as the graders see it.

    ``str``-valued so a status read out of a run's JSON compares and serialises
    exactly as the bare string did, while an unknown status is a ``ValueError``
    at the boundary instead of a silently ungraded edge.
    """

    ENTAILED = "entailed"
    PARTIAL = "partial"
    CONTRADICTORY = "contradictory"
    IRRELEVANT = "irrelevant"


class ClaimStatus(StrEnum):
    """Closed claim status set (spec §11.3). Only ``supported`` and ``derived``
    may render as an unqualified conclusion."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    DERIVED = "derived"
    UNSUPPORTED = "unsupported"


# The statuses each gate metric counts. ``citation_completeness`` is scored over
# RENDERED claims; ``entailment_precision`` over SUPPORTING citation edges.
RENDERED_CLAIM_STATUSES: frozenset[ClaimStatus] = frozenset(
    {ClaimStatus.SUPPORTED, ClaimStatus.DERIVED}
)
SUPPORTING_CITATION_STATUSES: frozenset[CitationStatus] = frozenset(
    {CitationStatus.ENTAILED, CitationStatus.PARTIAL}
)


@dataclass(frozen=True)
class GradedCitation:
    """One claim -> evidence edge as the eval side reads it back from a run."""

    evidence_id: str
    status: CitationStatus

    def __post_init__(self) -> None:
        # Accepts the bare string a run's JSON carries; normalises it to the
        # enum member so a caller cannot smuggle an unknown status through.
        object.__setattr__(self, "status", CitationStatus(self.status))

    @property
    def supporting(self) -> bool:
        return self.status in SUPPORTING_CITATION_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.evidence_id, "status": str(self.status)}


@dataclass(frozen=True)
class GradedClaim:
    """One graded claim: its status, its citation edges and its lineage.

    ``derived`` is the one status that asserts something the claim's own text
    does not carry — that the number was CALCULATED from cited operands — so it
    is the one status that cannot stand without ``calculation_lineage``. A
    lineage-less ``derived`` claim renders as an unqualified conclusion with
    nothing recording how it was reached, which is precisely what the status
    exists to make auditable.
    """

    text: str
    status: ClaimStatus
    citations: tuple[GradedCitation, ...] = ()
    calculation_lineage: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ClaimStatus(self.status))
        if self.status is ClaimStatus.DERIVED and not self.calculation_lineage:
            raise ValueError("a derived claim must carry calculation_lineage")

    @property
    def rendered(self) -> bool:
        """Whether this claim renders as an unqualified conclusion."""
        return self.status in RENDERED_CLAIM_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "status": str(self.status),
            "citations": [citation.to_dict() for citation in self.citations],
            "calculation_lineage": (
                dict(self.calculation_lineage) if self.calculation_lineage is not None else None
            ),
        }


@dataclass(frozen=True)
class Evidence:
    """One golden citation anchor and, once resolved, its stable evidence id."""

    accession: str
    form: str
    section: str
    quote: str
    evidence_id: str
    span_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "accession": self.accession,
            "form": self.form,
            "section": self.section,
            "quote": self.quote,
            "span_id": self.span_id,
        }


@dataclass(frozen=True)
class NumericAnswer:
    """A normalised numeric expected answer: inclusive Decimal range + tuple."""

    low: Decimal
    high: Decimal
    unit: str
    scale_exponent: int
    period: str

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"numeric answer range low {self.low} exceeds high {self.high}")
        if self.scale_exponent not in ALLOWED_SCALE_EXPONENTS:
            # A magnitude off by three orders is the failure mode this closed set
            # exists to make impossible, and it is invisible in the rendered
            # answer -- the digits are right and only the scale is wrong.
            raise ValueError(
                f"scale exponent {self.scale_exponent} is not one of "
                f"{sorted(ALLOWED_SCALE_EXPONENTS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "numeric",
            "low": f"{self.low:f}",
            "high": f"{self.high:f}",
            "unit": self.unit,
            "scale_exponent": self.scale_exponent,
            "period": self.period,
        }


@dataclass(frozen=True)
class TextAnswer:
    """A free-text expected answer."""

    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "text", "text": self.text}


ExpectedAnswer = NumericAnswer | TextAnswer


@dataclass(frozen=True)
class ManifestEntry:
    """One compiled, validated question."""

    id: str
    category: str
    issuer: dict[str, str]
    question: str
    as_of: str
    answerable: bool
    expected_answer: ExpectedAnswer | None
    evidence: tuple[Evidence, ...]
    documents_reviewed: tuple[str, ...]
    # Filings issued *after* ``as_of`` that a temporal-cutoff trap deliberately
    # references (the later revision the correct answer must ignore). Excluded
    # from the temporal-leakage check; ``documents_reviewed`` stays <= ``as_of``.
    future_revisions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # An answerable question with no expected answer or no gold evidence
        # cannot be graded, and a NEGATIVE case that declares an answer or cites
        # evidence is no longer a negative case -- either way the entry would be
        # scored against something it does not mean.
        if self.answerable:
            if self.expected_answer is None:
                raise ValueError(f"{self.id}: an answerable entry needs an expected_answer")
            if not self.evidence:
                raise ValueError(f"{self.id}: an answerable entry must cite evidence")
        else:
            if self.expected_answer is not None:
                raise ValueError(f"{self.id}: an unanswerable entry must have no expected_answer")
            if self.evidence:
                raise ValueError(f"{self.id}: an unanswerable entry must cite no evidence")
            if not self.documents_reviewed:
                raise ValueError(
                    f"{self.id}: an unanswerable entry must declare documents_reviewed"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "issuer": self.issuer,
            "question": self.question,
            "as_of": self.as_of,
            "answerable": self.answerable,
            "expected_answer": (
                self.expected_answer.to_dict() if self.expected_answer is not None else None
            ),
            "evidence": [e.to_dict() for e in self.evidence],
            "documents_reviewed": list(self.documents_reviewed),
            "future_revisions": list(self.future_revisions),
        }


@dataclass(frozen=True)
class Manifest:
    """The compiled, checksum-pinned smoke manifest."""

    corpus_version_id: str | None
    resolved: bool
    entries: tuple[ManifestEntry, ...]
    checksum: str = ""

    def __post_init__(self) -> None:
        # ``resolved`` is the claim that every golden quote was pinned to exactly
        # one span in the corpus. An entry whose evidence carries no ``span_id``
        # was never resolved, so a manifest holding one is asserting a
        # provenance it does not have -- the lineage half of the same rule the
        # ``derived`` claim status obeys.
        if not self.resolved:
            return
        for entry in self.entries:
            for evidence in entry.evidence:
                if evidence.span_id is None:
                    raise ValueError(
                        f"{entry.id}: resolved manifest carries unresolved evidence "
                        f"{evidence.evidence_id}"
                    )

    def body(self) -> dict[str, Any]:
        """Canonical body (everything the checksum covers, checksum excluded)."""
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "corpus_version_id": self.corpus_version_id,
            "resolved": self.resolved,
            "question_count": len(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "checksum": self.checksum}


__all__ = [
    "ALLOWED_SCALE_EXPONENTS",
    "MANIFEST_SCHEMA_VERSION",
    "RENDERED_CLAIM_STATUSES",
    "SCALE_EXPONENTS",
    "SUPPORTING_CITATION_STATUSES",
    "CitationStatus",
    "ClaimStatus",
    "Evidence",
    "GradedCitation",
    "GradedClaim",
    "ExpectedAnswer",
    "Manifest",
    "ManifestEntry",
    "NumericAnswer",
    "TextAnswer",
]
