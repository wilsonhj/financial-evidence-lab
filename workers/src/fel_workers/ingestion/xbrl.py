"""XBRL fact normalization (T0104).

Turns raw inline-XBRL occurrences into financial-fact/v1-shaped records:

- decimal string values (never binary floats), with the display scale
  applied so the stored value is the full unscaled amount (output scale 0);
- iXBRL transformation-registry formats resolved through a CLOSED registry
  (``_FORMAT_TRANSFORMS``): num-dot-decimal, num-comma-decimal, fixed-zero,
  fixed-empty (registry policy: reject, never silently zero), with
  parenthesized-negative and dash-as-zero handling; an UNKNOWN format fails
  closed with ``UNKNOWN_FORMAT`` — never a silent guess;
- non-finite decimals (NaN/sNaN/Infinity) rejected fail-closed;
- sign attributes resolved;
- units mapped from XBRL measures (iso4217:USD -> USD);
- instant/duration periods and explicit dimensions from the fact context;
- duplicate detection within a filing (identical fact key + value collapses
  onto the canonical row; conflicting values fail closed); and
- restatement linkage: a fact whose key matches an earlier filing's fact but
  whose value differs records ``restates`` -> the superseded fact id.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from fel_workers.ingestion.errors import NormalizationError, ReasonCode
from fel_workers.ingestion.parser import ID_NAMESPACE, InlineFact, ParsedDocument

__all__ = [
    "NORMALIZER_VERSION",
    "NormalizationError",
    "PriorFact",
    "NormalizedFact",
    "decimal_str",
    "map_unit",
    "parse_fact_value",
    "fact_key",
    "normalize_facts",
]

NORMALIZER_VERSION = "fel-xbrl/1.0.0"

_UNIT_MEASURES = {
    "iso4217:usd": "USD",
    "iso4217:eur": "EUR",
    "iso4217:gbp": "GBP",
    "iso4217:jpy": "JPY",
    "xbrli:shares": "shares",
    "shares": "shares",
    "xbrli:pure": "pure",
    "pure": "pure",
}


@dataclass(frozen=True)
class PriorFact:
    """Canonical fact from an earlier published document version."""

    fact_id: str
    value: str


@dataclass(frozen=True)
class NormalizedFact:
    """financial-fact/v1 record plus persistence-side linkage fields."""

    id: str
    entity_id: str
    document_version_id: str
    concept: str
    label: str | None
    value: str
    unit: str
    scale: int
    period_type: str
    period_instant: date | None
    period_start: date | None
    period_end: date | None
    dimensions: Mapping[str, str]
    source_span_id: str
    reported_or_derived: str
    confidence: float
    fact_key: str
    duplicate_of: str | None
    restates: str | None

    def to_contract(self) -> dict[str, object]:
        """Contract financial-fact/v1 shape (value as decimal string)."""
        period: dict[str, object] = {"type": self.period_type}
        if self.period_type == "instant" and self.period_instant is not None:
            period["instant"] = self.period_instant.isoformat()
        if self.period_start is not None:
            period["start"] = self.period_start.isoformat()
        if self.period_end is not None:
            period["end"] = self.period_end.isoformat()
        record: dict[str, object] = {
            "entity_id": self.entity_id,
            "concept": self.concept,
            "value": self.value,
            "unit": self.unit,
            "scale": self.scale,
            "period": period,
            "dimensions": dict(self.dimensions),
            "source_span_id": self.source_span_id,
            "reported_or_derived": self.reported_or_derived,
            "confidence": self.confidence,
        }
        if self.label is not None:
            record["label"] = self.label
        return record


def decimal_str(value: Decimal) -> str:
    """Render a Decimal as the contract's plain decimal string (no exponent)."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def map_unit(measure: str) -> str:
    """Map an XBRL measure to the contract unit label."""
    return _UNIT_MEASURES.get(measure.lower(), measure)


class _ValueRejected(Exception):
    """Internal: a transform rejects the value with a stable reason code."""

    def __init__(self, reason_code: ReasonCode, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


# Dash glyphs commonly used for "zero / not applicable" in filings.
_DASH_TEXTS = frozenset({"-", "‐", "–", "—", "−"})


def _numeric(text: str, *, thousands: str, decimal_sep: str) -> Decimal:
    """Shared numeric transform body with dash-as-zero handling."""
    if text in _DASH_TEXTS:
        return Decimal(0)
    cleaned = text.replace(" ", "").replace(" ", "").replace(thousands, "")
    if decimal_sep != ".":
        cleaned = cleaned.replace(decimal_sep, ".")
    if not cleaned:
        raise _ValueRejected(ReasonCode.EMPTY_FACT_VALUE, "has no numeric text")
    return Decimal(cleaned)  # InvalidOperation propagates to the caller


def _num_dot_decimal(text: str) -> Decimal:
    """ixt:num-dot-decimal — ',' thousands, '.' decimal (e.g. '1,234.56')."""
    return _numeric(text, thousands=",", decimal_sep=".")


def _num_comma_decimal(text: str) -> Decimal:
    """ixt:num-comma-decimal — '.' thousands, ',' decimal (e.g. '1.234,56')."""
    return _numeric(text, thousands=".", decimal_sep=",")


def _fixed_zero(text: str) -> Decimal:
    """ixt:fixed-zero — the value is zero regardless of the display text."""
    return Decimal(0)


def _fixed_empty(text: str) -> Decimal:
    """ixt:fixed-empty — REGISTRY POLICY: reject, never silently zero.

    fixed-empty declares "this element carries no numeric value"; storing 0
    would fabricate a number, so it fails closed into quarantine.
    """
    raise _ValueRejected(
        ReasonCode.EMPTY_FACT_VALUE,
        "uses ixt:fixed-empty (declares no numeric value); registry policy " "is reject, not zero",
    )


# CLOSED transform registry, keyed by the format's local name (namespace
# prefix stripped, lowercased). Formats outside the registry — including
# ixt:num-unit-decimal, deliberately unregistered — fail closed with
# UNKNOWN_FORMAT; a transform must be added here before such filings ingest.
_FORMAT_TRANSFORMS: dict[str, Callable[[str], Decimal]] = {
    "num-dot-decimal": _num_dot_decimal,
    "numdotdecimal": _num_dot_decimal,
    "num-comma-decimal": _num_comma_decimal,
    "numcommadecimal": _num_comma_decimal,
    "fixed-zero": _fixed_zero,
    "fixedzero": _fixed_zero,
    "fixed-empty": _fixed_empty,
    "fixedempty": _fixed_empty,
    "zerodash": lambda text: Decimal(0),
    "numdash": lambda text: Decimal(0),
}


def parse_fact_value(fact: InlineFact) -> Decimal:
    """Resolve display text + format + sign + scale into the unscaled value.

    The fact's iXBRL ``format`` attribute selects a transform from the
    closed registry; a fact without a format gets the plain num-dot-decimal
    rendering. Parenthesized values ('(1,234)') are negative; a lone dash is
    zero; non-finite decimals (NaN/sNaN/Infinity) are rejected fail-closed
    so they can never reach the database CHECK constraint.
    """
    transform: Callable[[str], Decimal] = _num_dot_decimal
    if fact.format is not None:
        local = fact.format.rsplit(":", 1)[-1].strip().lower()
        registered = _FORMAT_TRANSFORMS.get(local)
        if registered is None:
            raise NormalizationError(
                ReasonCode.UNKNOWN_FORMAT,
                f"fact '{fact.concept}' uses unregistered iXBRL format "
                f"{fact.format!r}; add a transform to the registry before "
                "ingesting (fail closed — a guessed locale corrupts "
                "magnitudes silently)",
            )
        transform = registered
    text = fact.raw_text.strip()
    negative = False
    if len(text) >= 2 and text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    try:
        magnitude = transform(text)
        if not magnitude.is_finite():
            raise NormalizationError(
                ReasonCode.NONFINITE_FACT_VALUE,
                f"fact '{fact.concept}' has non-finite value "
                f"{fact.raw_text!r}; NaN/Infinity are never storable",
            )
        if negative:
            magnitude = -magnitude
        if fact.sign == "-":
            magnitude = -magnitude
        # scaleb stays inside the try: exotic operands signal
        # InvalidOperation and must fail closed, not crash the run.
        return magnitude.scaleb(fact.scale)
    except _ValueRejected as exc:
        raise NormalizationError(
            exc.reason_code,
            f"fact '{fact.concept}' at chars {fact.start_char}-" f"{fact.end_char} {exc.detail}",
        ) from exc
    except InvalidOperation as exc:
        raise NormalizationError(
            ReasonCode.UNPARSEABLE_FACT_VALUE,
            f"fact '{fact.concept}' has unparseable value {fact.raw_text!r}",
        ) from exc


def fact_key(
    concept: str,
    unit: str,
    *,
    period_type: str,
    period_instant: date | None,
    period_start: date | None,
    period_end: date | None,
    dimensions: Mapping[str, str],
) -> str:
    """Deterministic dedupe/restatement key (concept, unit, period, dims)."""
    period_repr = (
        f"instant:{period_instant}"
        if period_type == "instant"
        else f"duration:{period_start}:{period_end}"
    )
    dims_repr = ";".join(f"{k}={dimensions[k]}" for k in sorted(dimensions))
    return f"{concept}|{unit}|{period_repr}|{dims_repr}"


def normalize_facts(
    parsed: ParsedDocument,
    *,
    entity_id: str,
    document_version_id: str,
    prior_facts: Mapping[str, PriorFact] | None = None,
) -> list[NormalizedFact]:
    """Normalize a parsed filing's inline facts (see module docstring).

    ``prior_facts`` maps fact keys to the latest canonical fact from earlier
    published filings of the same entity; a differing value records the
    restatement linkage.
    """
    prior = prior_facts or {}
    canonical: dict[str, NormalizedFact] = {}
    out: list[NormalizedFact] = []
    for fact in parsed.facts:
        context = parsed.contexts[fact.context_ref]
        measure = parsed.units[fact.unit_ref]
        unit = map_unit(measure)
        value = parse_fact_value(fact)
        if context.instant is not None:
            period_type = "instant"
            period_instant: date | None = context.instant
            period_start = period_end = None
        elif context.start is not None and context.end is not None:
            period_type = "duration"
            period_instant = None
            period_start, period_end = context.start, context.end
        else:
            raise NormalizationError(
                ReasonCode.INVALID_PERIOD_STRUCTURE,
                f"context '{context.id}' for fact '{fact.concept}' has "
                "neither an instant nor a complete start/end duration",
            )
        key = fact_key(
            fact.concept,
            unit,
            period_type=period_type,
            period_instant=period_instant,
            period_start=period_start,
            period_end=period_end,
            dimensions=context.dimensions,
        )
        value_text = decimal_str(value)
        duplicate_of: str | None = None
        existing = canonical.get(key)
        if existing is not None:
            if existing.value != value_text:
                raise NormalizationError(
                    ReasonCode.INCONSISTENT_DUPLICATE,
                    f"fact '{fact.concept}' ({key}) appears twice with "
                    f"conflicting values {existing.value} (span "
                    f"{existing.source_span_id}) and {value_text} (span "
                    f"{fact.span_id}); the filing needs manual review",
                )
            duplicate_of = existing.id
        restates: str | None = None
        earlier = prior.get(key)
        if earlier is not None and earlier.value != value_text:
            restates = earlier.fact_id
        ordinal = len(out)
        normalized = NormalizedFact(
            id=str(uuid.uuid5(ID_NAMESPACE, f"{document_version_id}|fact|{ordinal}|{key}")),
            entity_id=entity_id,
            document_version_id=document_version_id,
            concept=fact.concept,
            label=None,
            value=value_text,
            unit=unit,
            scale=0,
            period_type=period_type,
            period_instant=period_instant,
            period_start=period_start,
            period_end=period_end,
            dimensions=MappingProxyType(dict(context.dimensions)),
            source_span_id=fact.span_id,
            reported_or_derived="reported",
            confidence=1.0,
            fact_key=key,
            duplicate_of=duplicate_of,
            restates=restates,
        )
        if duplicate_of is None:
            canonical[key] = normalized
        out.append(normalized)
    return out
