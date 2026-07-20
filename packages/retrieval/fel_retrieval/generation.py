"""Structured answer generation into atomic, closed-state claims (M2-020 / T0207).

The reader is decomposed into two deterministic seams so the pipeline can run
mock-first in CI and swap in a live model without any wiring change:

* ``StructuredClaimGenerator`` builds a JSON-Schema-constrained request from the
  question and the *selected* context items and hands it to the frozen
  ``StructuredLLMProvider`` protocol (``fel_providers``). The provider result
  supplies the usage/refusal metadata that the run's budget records; a refusal
  fails the answer closed (no claims), never a fabricated one.
* The claim *decomposition* itself is deterministic: every selected context item
  yields exactly one atomic claim grounded in that item, cited back to the item's
  accepted evidence span. This is the property M2 verification (M2-021/022) then
  classifies — the generator never asserts support it has not grounded, so a
  claim can only cite evidence that fusion actually accepted.

Claims carry the spec §11.3 closed status set
(``supported|partially_supported|contradicted|derived|unsupported``). Because a
mock claim is a verbatim span of the evidence it cites, the generator grounds it
as ``supported`` with an ``entailed`` citation edge. Formal citation
classification, deterministic numeric-tuple checking and cross-version integrity
are the verifier's job (M2-021), which re-derives every edge from the evidence;
the generator only proposes atomic claims that cite accepted context. All
arithmetic-bearing fields are ``Decimal`` end-to-end (house rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fel_providers.interfaces import (
    StructuredGenerationRequest,
    StructuredLLMProvider,
)

# Closed claim status set (spec §11.3 / claim.schema.json). Only ``supported``
# and ``derived`` may render as unqualified conclusions downstream.
CLAIM_STATUSES: frozenset[str] = frozenset(
    {"supported", "partially_supported", "contradicted", "derived", "unsupported"}
)

# Closed citation-edge status set (spec §11 / retrieval-trace citations).
CITATION_STATUSES: frozenset[str] = frozenset(
    {"entailed", "partial", "contradictory", "irrelevant"}
)

# Structured-generation schema identity. Pinned so a live provider constrains its
# output to the same shape the mock is exercised against.
CLAIM_SCHEMA_NAME = "retrieval-claims"
CLAIM_SCHEMA_VERSION = "v1"

# JSON schema handed to the provider: an ordered list of atomic claims, each
# citing one or more selected context items by id. Mirrors the trace contract's
# retrievalClaim/retrievalCitation shapes without importing them.
CLAIM_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "citations"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "citations": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "minItems": 1,
                    },
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "You are a financial evidence reader. Decompose the answer into atomic, "
    "independently verifiable claims. Every claim must cite the selected context "
    "items it is grounded in. Do not assert anything not present in the context."
)


@dataclass(frozen=True)
class NumericTuple:
    """A financial fact's checkable numeric tuple (spec §11.4 provenance).

    ``value`` and ``scale`` are exact ``Decimal`` s; ``scale`` is the base-ten
    exponent applied to ``value`` (``0`` for a plain number, ``6`` for millions).
    ``sign`` is derived from ``value`` so it can be compared independently.
    """

    value: Decimal
    unit: str
    period: str
    scale: int

    @property
    def sign(self) -> int:
        if self.value > 0:
            return 1
        if self.value < 0:
            return -1
        return 0


@dataclass(frozen=True)
class ContextItem:
    """One selected (accepted) context item the generator may ground a claim in."""

    item_id: str
    kind: str
    text: str
    source_span_id: str
    document_version_id: str
    financial_fact_id: str | None = None
    numeric: NumericTuple | None = None


@dataclass(frozen=True)
class ClaimCitation:
    """One claim -> evidence edge. ``status``/``numeric_checks`` and the
    ``verifier``/``model``/``version`` provenance are (re)set by verification
    (M2-021); the generator only fills ``status`` from its verbatim grounding."""

    item_id: str
    source_span_id: str
    status: str = "irrelevant"
    numeric_checks: dict[str, bool] = field(default_factory=dict)
    rationale: str | None = None
    verifier: str | None = None
    model: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class GeneratedClaim:
    """An atomic claim in the closed status set with its candidate citations."""

    ord: int
    text: str
    status: str
    citations: tuple[ClaimCitation, ...]
    confidence: Decimal | None = None
    calculation_lineage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in CLAIM_STATUSES:
            raise ValueError(f"illegal claim status: {self.status!r}")
        for citation in self.citations:
            if citation.status not in CITATION_STATUSES:
                raise ValueError(f"illegal citation status: {citation.status!r}")


@dataclass(frozen=True)
class GenerationResult:
    """The generated claim set plus the provider's usage/refusal metadata."""

    claims: tuple[GeneratedClaim, ...]
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    refused: bool
    refusal: str | None = None


def _render_context(context: Sequence[ContextItem]) -> str:
    lines = []
    for item in context:
        lines.append(f"[{item.item_id}] ({item.kind}) {item.text}")
    return "\n".join(lines)


def _render_prompt(question: str, context: Sequence[ContextItem], as_of: str) -> str:
    return (
        f"As-of: {as_of}\nQuestion: {question}\n\nSelected context:\n" f"{_render_context(context)}"
    )


class StructuredClaimGenerator:
    """Generates atomic claims from selected context via a StructuredLLMProvider.

    The provider call is load-bearing for the run's usage/refusal record; the
    atomic decomposition is deterministic (one claim per selected item) so mock
    and live runs persist the same shape and the same evidence linkage.
    """

    def __init__(self, provider: StructuredLLMProvider, *, max_output_tokens: int = 1024) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be >= 1")
        self._provider = provider
        self._max_output_tokens = max_output_tokens

    def generate(
        self, question: str, context: Sequence[ContextItem], *, as_of: str
    ) -> GenerationResult:
        request = StructuredGenerationRequest(
            schema_name=CLAIM_SCHEMA_NAME,
            schema_version=CLAIM_SCHEMA_VERSION,
            json_schema=CLAIM_JSON_SCHEMA,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _render_prompt(question, context, as_of)},
            ],
            max_output_tokens=self._max_output_tokens,
        )
        result = self._provider.generate_structured(request)
        if result.refused:
            return GenerationResult(
                claims=(),
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                refused=True,
                refusal=result.refusal,
            )
        claims = _decompose(context)
        return GenerationResult(
            claims=claims,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            refused=False,
        )


def _decompose(context: Sequence[ContextItem]) -> tuple[GeneratedClaim, ...]:
    """One atomic claim per selected item, verbatim-grounded in that item.

    A mock claim is a verbatim span of its cited evidence, so the edge is
    trivially ``entailed`` and the claim ``supported``. Verification (M2-021)
    re-derives every edge from the evidence (numeric checks, integrity) rather
    than trusting this grounding.
    """
    claims: list[GeneratedClaim] = []
    for ord_, item in enumerate(context):
        citation = ClaimCitation(
            item_id=item.item_id,
            source_span_id=item.source_span_id,
            status="entailed",
        )
        claims.append(
            GeneratedClaim(
                ord=ord_,
                text=item.text,
                status="supported",
                citations=(citation,),
                confidence=Decimal("1"),
            )
        )
    return tuple(claims)


__all__ = [
    "CITATION_STATUSES",
    "CLAIM_JSON_SCHEMA",
    "CLAIM_SCHEMA_NAME",
    "CLAIM_SCHEMA_VERSION",
    "CLAIM_STATUSES",
    "ClaimCitation",
    "ContextItem",
    "GeneratedClaim",
    "GenerationResult",
    "NumericTuple",
    "StructuredClaimGenerator",
]
