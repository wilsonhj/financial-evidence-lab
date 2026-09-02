"""Structured answer generation into atomic, closed-state claims (M2-020 / T0207, #193).

The reader is one deterministic seam: ``StructuredClaimGenerator`` builds a
JSON-Schema-constrained request from the question and the *selected* context
items, hands it to the frozen ``StructuredLLMProvider`` protocol
(``fel_providers``), and then **consumes the provider's JSON**. The schema is
``claims-output/v1`` (``packages/contracts/schemas/claims-output.schema.json``),
mirrored here as :data:`CLAIM_JSON_SCHEMA` so the package stays importable
without the contracts workspace and so the same object can be sent to a strict
structured-output provider unchanged.

Everything about that consumption fails closed:

* Output that does not validate against ``claims-output/v1`` raises
  :class:`GenerationContractError`. There is no lenient parse and no partial
  admission — a malformed answer is an abstention, not a smaller answer.
* A citation whose ``item_id`` is not one of the selected context items is a
  contract violation, not a soft failure: it is the shape a fabricated citation
  takes, and admitting it would let the model widen its own evidence set.
* A citation ``quote`` that is not a span of the cited item's text is the same
  violation seen from the other side — a real id with invented evidence text.
* An explicit ``abstain`` yields zero claims and records the reason. A refusal
  from the provider does the same via ``refused``; neither ever produces a
  fabricated claim.

The generator only *proposes* claims: every claim leaves here ``unsupported``
with ``irrelevant`` citation edges and ``confidence`` unset. Verification
(M2-021, :mod:`fel_retrieval.verification`) re-derives each edge from the cited
evidence and sets both the status and the confidence, so a rendered conclusion
can never outrun what the evidence supports and no claim can carry a constant
confidence of 1 that nothing checked.

Claims carry the spec §11.3 closed status set
(``supported|partially_supported|contradicted|derived|unsupported``). All
arithmetic-bearing fields are ``Decimal`` end-to-end (house rule).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
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

# Structured-generation schema identity: the contract schema the provider is
# constrained to and the generator validates against.
CLAIM_SCHEMA_NAME = "claims-output"
CLAIM_SCHEMA_VERSION = "v1"

# Mirror of packages/contracts/schemas/claims-output.schema.json (body only —
# no $id/$schema/x-fel-version/title, which a provider does not need). Optional
# members are required-and-nullable so this object is accepted verbatim by a
# strict structured-output provider. A test pins it to the contract file.
CLAIM_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims", "abstain"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "citations", "numeric"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["item_id", "quote"],
                            "properties": {
                                "item_id": {"type": "string", "minLength": 1},
                                "quote": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "numeric": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "required": ["value", "unit", "period"],
                        "properties": {
                            "value": {"type": "string", "minLength": 1},
                            "unit": {"type": ["string", "null"]},
                            "period": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
        "abstain": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["reason"],
            "properties": {"reason": {"type": "string", "minLength": 1}},
        },
    },
}

_SYSTEM_PROMPT = (
    "You are a financial evidence reader. Decompose the answer into atomic, "
    "independently verifiable claims. Every claim must cite the selected context "
    "items it is grounded in by their bracketed id, and quote the exact span of "
    "that item which grounds it. Do not assert anything not present in the "
    "context; if the context does not answer the question, abstain."
)

_WHITESPACE = re.compile(r"\s+")


class GenerationContractError(RuntimeError):
    """The provider's claims JSON violates ``claims-output/v1``.

    Carries a ``code`` so the caller can record a typed rejection event and end
    the run abstained rather than surfacing a partial answer.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NumericTuple:
    """A financial fact's checkable numeric tuple (spec §11.4 provenance).

    ``value`` is an exact ``Decimal``; ``scale`` is an ``int`` base-ten exponent
    applied to ``value`` (``0`` for a plain number, ``6`` for millions).
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
    (M2-021); the generator fills only ``item_id``/``source_span_id``/``quote``."""

    item_id: str
    source_span_id: str
    status: str = "irrelevant"
    numeric_checks: dict[str, bool] = field(default_factory=dict)
    rationale: str | None = None
    verifier: str | None = None
    model: str | None = None
    version: str | None = None
    quote: str | None = None


@dataclass(frozen=True)
class GeneratedClaim:
    """An atomic claim in the closed status set with its candidate citations.

    ``numeric`` is the single value the claim itself asserts (an atomic claim
    asserts one quantity). Verification checks it against each cited item's own
    evidence, so a corroborating fact passes and a disagreeing one contradicts.
    It is ``None`` for a claim that asserts no single checkable scalar (a passage
    claim, or an aggregate that only lists its operands).

    ``confidence`` is set by verification, never by the generator.
    """

    ord: int
    text: str
    status: str
    citations: tuple[ClaimCitation, ...]
    confidence: Decimal | None = None
    calculation_lineage: dict[str, Any] = field(default_factory=dict)
    numeric: NumericTuple | None = None

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
    abstained: bool = False
    abstain_reason: str | None = None


def _normalize(text: str) -> str:
    """Collapse whitespace; the prompt and the quote check share this form."""
    return _WHITESPACE.sub(" ", text).strip()


def _render_context(context: Sequence[ContextItem]) -> str:
    """Render the selected items as one line each, id first.

    Line shape (whitespace-collapsed so one item is always one line)::

        [<item_id>] (<kind>) [numeric value=.. unit=.. period=.. scale=..] <text>

    The numeric marker is present only for an item that carries a numeric tuple.
    A deterministic mock provider parses this block back (see
    ``fel_providers.mocks``), which is why the format is machine-readable as
    well as legible to a live model.
    """
    lines = []
    for item in context:
        marker = ""
        if item.numeric is not None:
            marker = (
                f"[numeric value={item.numeric.value} unit={item.numeric.unit}"
                f" period={item.numeric.period} scale={item.numeric.scale}] "
            )
        lines.append(f"[{item.item_id}] ({item.kind}) {marker}{_normalize(item.text)}")
    return "\n".join(lines)


def _render_prompt(question: str, context: Sequence[ContextItem], as_of: str) -> str:
    return (
        f"As-of: {as_of}\nQuestion: {question}\n\nSelected context:\n" f"{_render_context(context)}"
    )


# --- strict validation of claims-output/v1 ---------------------------------
# jsonschema is not a dependency of this repository and the worker's hand-rolled
# checker lives in a package this one must not depend on, so the schema subset
# used by CLAIM_JSON_SCHEMA is enforced here: type (including nullable unions),
# required, properties, additionalProperties: false, items, minItems, minLength.


def _type_ok(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _schema_errors(value: object, schema: Mapping[str, Any], *, path: str) -> list[str]:
    """Return every violation of ``schema`` by ``value`` (empty list = valid).

    Error text names schema locations and JSON types only: provider output is
    model text and must never reach a log or an exception message.
    """
    errors: list[str] = []
    expected = schema.get("type")
    types = [expected] if isinstance(expected, str) else expected
    if isinstance(types, list):
        if not any(isinstance(t, str) and _type_ok(value, t) for t in types):
            errors.append(f"{path}: expected {'|'.join(str(t) for t in types)}")
            return errors

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path}: string shorter than minLength {min_length}")

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(f"{path}: missing required property {key!r}")
        properties_raw = schema.get("properties")
        properties = properties_raw if isinstance(properties_raw, dict) else {}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                errors.extend(_schema_errors(child, child_schema, path=f"{path}.{key}"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: array shorter than minItems {min_items}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, path=f"{path}[{index}]"))

    return errors


def validate_claims_output(parsed: Mapping[str, Any]) -> None:
    """Raise :class:`GenerationContractError` unless ``parsed`` is claims-output/v1."""
    errors = _schema_errors(parsed, CLAIM_JSON_SCHEMA, path="$")
    if errors:
        raise GenerationContractError(
            "CLAIMS_OUTPUT_SCHEMA_INVALID",
            f"provider claims output failed {CLAIM_SCHEMA_NAME}/{CLAIM_SCHEMA_VERSION}"
            f" validation: {errors[0]}",
        )


def _numeric_from(
    raw: Mapping[str, Any], evidence: ContextItem | None, *, path: str
) -> NumericTuple:
    """Build the claim's asserted numeric tuple from provider JSON.

    ``value`` is the model's assertion, parsed as an exact ``Decimal``. ``unit``
    and ``period`` fall back to the first cited item's own tuple when the model
    leaves them null, and ``scale`` always comes from the evidence: the base-ten
    exponent is a normalization artifact of ingestion, not something the contract
    asks a model to assert, so inventing one here would manufacture a mismatch.
    A claim whose cited evidence has no numeric tuple keeps neutral defaults and
    is graded non-supporting by the verifier.
    """
    reference = evidence.numeric if evidence is not None else None
    raw_value = raw.get("value")
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as exc:
        raise GenerationContractError(
            "CLAIM_NUMERIC_NOT_DECIMAL",
            f"{path}: claim numeric value is not a decimal string",
        ) from exc
    unit = raw.get("unit")
    period = raw.get("period")
    return NumericTuple(
        value=value,
        unit=str(unit) if isinstance(unit, str) else (reference.unit if reference else ""),
        period=str(period) if isinstance(period, str) else (reference.period if reference else ""),
        scale=reference.scale if reference else 0,
    )


class StructuredClaimGenerator:
    """Generates atomic claims from selected context via a ``StructuredLLMProvider``.

    The provider call is load-bearing twice over: it supplies the run's
    usage/refusal record *and* the claims themselves. ``identity_mode=True``
    restores the historical mock-first behaviour (see :func:`_decompose`).
    """

    def __init__(
        self,
        provider: StructuredLLMProvider,
        *,
        max_output_tokens: int = 1024,
        identity_mode: bool = False,
    ) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be >= 1")
        self._provider = provider
        self._max_output_tokens = max_output_tokens
        self._identity_mode = identity_mode

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

        if self._identity_mode:
            claims = _decompose(context)
            abstain_reason = None
        else:
            claims, abstain_reason = _claims_from(result.parsed, context)

        return GenerationResult(
            claims=claims,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            refused=False,
            abstained=abstain_reason is not None,
            abstain_reason=abstain_reason,
        )


def _claims_from(
    parsed: Mapping[str, Any] | None, context: Sequence[ContextItem]
) -> tuple[tuple[GeneratedClaim, ...], str | None]:
    """Map validated provider JSON onto proposed claims (fail closed)."""
    if parsed is None:
        raise GenerationContractError(
            "CLAIMS_OUTPUT_MISSING",
            "provider returned no parsed object and did not refuse",
        )
    validate_claims_output(parsed)

    abstain = parsed.get("abstain")
    if isinstance(abstain, dict):
        reason = abstain.get("reason")
        return (), str(reason) if isinstance(reason, str) else "unspecified"

    accepted = {item.item_id: item for item in context}
    raw_claims = parsed.get("claims")
    claims: list[GeneratedClaim] = []
    for ord_, raw_claim in enumerate(raw_claims if isinstance(raw_claims, list) else []):
        path = f"$.claims[{ord_}]"
        citations: list[ClaimCitation] = []
        first_cited: ContextItem | None = None
        for index, raw_citation in enumerate(raw_claim["citations"]):
            item_id = str(raw_citation["item_id"])
            item = accepted.get(item_id)
            if item is None:
                # A citation to an item outside the selected set is the shape a
                # fabricated citation takes; admitting it would let the model
                # widen its own evidence set.
                raise GenerationContractError(
                    "UNKNOWN_CONTEXT_ITEM",
                    f"{path}.citations[{index}]: item {item_id} is not a selected context item",
                )
            quote = str(raw_citation["quote"])
            if _normalize(quote).lower() not in _normalize(item.text).lower():
                raise GenerationContractError(
                    "QUOTE_NOT_IN_CONTEXT_ITEM",
                    f"{path}.citations[{index}]: quote is not a span of item {item_id}",
                )
            if first_cited is None:
                first_cited = item
            citations.append(
                ClaimCitation(
                    item_id=item.item_id,
                    source_span_id=item.source_span_id,
                    quote=quote,
                )
            )
        raw_numeric = raw_claim.get("numeric")
        numeric = (
            _numeric_from(raw_numeric, first_cited, path=path)
            if isinstance(raw_numeric, dict)
            else None
        )
        claims.append(
            GeneratedClaim(
                # Proposed only: verification assigns the status, the citation
                # edges and the confidence from the evidence itself.
                ord=ord_,
                text=str(raw_claim["text"]),
                status="unsupported",
                citations=tuple(citations),
                confidence=None,
                numeric=numeric,
            )
        )
    return tuple(claims), None


def _decompose(context: Sequence[ContextItem]) -> tuple[GeneratedClaim, ...]:
    """TEST SHIM ONLY — historical identity mapping, off by default.

    Reachable only via ``StructuredClaimGenerator(..., identity_mode=True)``. It
    ignores the provider's structured JSON and emits one claim per selected item,
    verbatim-grounded in that item, which is what the pipeline did before #193.
    It exists so a test can exercise downstream stages against a fixed claim set
    without a provider fixture; it must never be used on a real run, where it
    would report model output that the model never produced.
    """
    claims: list[GeneratedClaim] = []
    for ord_, item in enumerate(context):
        citation = ClaimCitation(
            item_id=item.item_id,
            source_span_id=item.source_span_id,
            quote=item.text,
        )
        claims.append(
            GeneratedClaim(
                ord=ord_,
                text=item.text,
                status="unsupported",
                citations=(citation,),
                confidence=None,
                numeric=item.numeric,
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
    "GenerationContractError",
    "GenerationResult",
    "NumericTuple",
    "StructuredClaimGenerator",
    "validate_claims_output",
]
