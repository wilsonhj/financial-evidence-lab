"""XBRL fact normalization (T0104).

Turns raw inline-XBRL occurrences into financial-fact/v1-shaped records:

- decimal string values (never binary floats), with the display scale
  applied so the stored value is the full unscaled amount (output scale 0);
- sign attributes and locale formatting (thousands separators) resolved;
- units mapped from XBRL measures (iso4217:USD -> USD);
- instant/duration periods and explicit dimensions from the fact context;
- duplicate detection within a filing (identical fact key + value collapses
  onto the canonical row; conflicting values fail closed); and
- restatement linkage: a fact whose key matches an earlier filing's fact but
  whose value differs records ``restates`` -> the superseded fact id.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from fel_workers.ingestion.parser import ID_NAMESPACE, InlineFact, ParsedDocument

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


class NormalizationError(Exception):
    """Fact cannot be normalized; carries a stable code and diagnostic."""

    def __init__(self, reason_code: str, diagnostic: str) -> None:
        super().__init__(diagnostic)
        self.reason_code = reason_code
        self.diagnostic = diagnostic


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


def parse_fact_value(fact: InlineFact) -> Decimal:
    """Resolve display text + sign + scale into the unscaled decimal value."""
    cleaned = fact.raw_text.replace(",", "").replace(" ", "").strip()
    if not cleaned:
        raise NormalizationError(
            "EMPTY_FACT_VALUE",
            f"fact '{fact.concept}' at chars {fact.start_char}-{fact.end_char} "
            "has no numeric text",
        )
    try:
        magnitude = Decimal(cleaned)
    except InvalidOperation as exc:
        raise NormalizationError(
            "UNPARSEABLE_FACT_VALUE",
            f"fact '{fact.concept}' has unparseable value {fact.raw_text!r}",
        ) from exc
    if fact.sign == "-":
        magnitude = -magnitude
    return magnitude.scaleb(fact.scale)


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
                "INVALID_PERIOD",
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
                    "INCONSISTENT_DUPLICATE",
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
