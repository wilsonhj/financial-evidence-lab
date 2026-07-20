"""Typed seed records and compiled-manifest shapes (M2-023 / T0214a).

The raw seed (``evals/datasets/benchmark-seed/questions.jsonl``, reconciled from
PR #74) is untyped JSONL. These dataclasses give the compiler a checked view of
one record and of the checksum-pinned manifest it emits. All arithmetic-bearing
fields are exact ``Decimal`` strings end-to-end (house rule); ranges normalise to
an inclusive ``[low, high]`` (a point answer has ``low == high``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Human scale words -> base-ten exponent. The pinned closed set; an unknown scale
# fails compilation (a silently-wrong magnitude is the exact bug this guards).
SCALE_EXPONENTS: dict[str, int] = {"ones": 0, "thousands": 3, "millions": 6, "billions": 9}

MANIFEST_SCHEMA_VERSION = "m2-smoke-manifest/v1"


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
    "MANIFEST_SCHEMA_VERSION",
    "SCALE_EXPONENTS",
    "Evidence",
    "ExpectedAnswer",
    "Manifest",
    "ManifestEntry",
    "NumericAnswer",
    "TextAnswer",
]
