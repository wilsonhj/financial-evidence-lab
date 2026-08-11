"""Normalize extraction-payload proposals with Decimal (retain raw_value)."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from fel_workers.extraction.normalize.currency import normalize_currency
from fel_workers.extraction.normalize.dimensions import normalize_dimensions
from fel_workers.extraction.normalize.numeric import format_decimal, parse_numeric
from fel_workers.extraction.normalize.period import normalize_period
from fel_workers.extraction.types import NORMALIZER_BLOCKERS_KEY, NORMALIZER_VERSION
from fel_workers.extraction.validate.range import scale_blockers

_DRIVER_CATEGORIES = frozenset(
    {
        "price",
        "volume",
        "mix",
        "acquisition",
        "retention",
        "usage",
        "seats",
        "fx",
        "services",
        "cost",
        "other",
    }
)


def normalize_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy; never mutates input; never uses float."""
    if not isinstance(raw, dict):
        raise ValueError("payload must be an object")
    out = copy.deepcopy(raw)
    out["schema_version"] = "extraction-payload/v1"
    kind = out.get("kind")
    if kind not in {"kpi", "guidance", "revenue_driver"}:
        raise ValueError(f"unknown kind: {kind!r}")

    raw_value = out.get("raw_value")
    if not isinstance(raw_value, str):
        raise ValueError("raw_value must be a string")
    # Retain issuer wording exactly.
    out["raw_value"] = raw_value

    if "period" in out:
        out["period"] = normalize_period(out.get("period"))
    out["dimensions"], dimension_blockers = normalize_dimensions(out.get("dimensions"))
    # Recorded here rather than inside `_normalize_numeric_fields`, which is the
    # only other place that records blockers but never runs for qualitative
    # guidance or a revenue driver — both of which carry `dimensions`.
    _record_blockers(out, dimension_blockers)
    out["qualifiers"] = _normalize_qualifiers(out.get("qualifiers"))

    if kind == "kpi":
        _normalize_numeric_fields(out, value_keys=("value",))
    elif kind == "guidance":
        shape = out.get("shape")
        if shape == "point":
            _normalize_numeric_fields(out, value_keys=("value",))
        elif shape == "range":
            _normalize_numeric_fields(out, value_keys=("low", "high"))
        elif shape == "floor":
            _normalize_numeric_fields(out, value_keys=("low",))
        elif shape == "ceiling":
            _normalize_numeric_fields(out, value_keys=("high",))
        elif shape == "qualitative":
            text = out.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("qualitative guidance requires text")
            out["text"] = text.strip()
        else:
            raise ValueError(f"unknown guidance shape: {shape!r}")
        out["reported_or_derived"] = "management_assertion"
    else:
        category = out.get("category")
        if category not in _DRIVER_CATEGORIES:
            raise ValueError(f"unknown revenue_driver category: {category!r}")
        desc = out.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError("revenue_driver requires description")
        out["description"] = desc.strip()
        direction = out.get("direction", "unknown")
        if direction not in {"positive", "negative", "mixed", "unknown"}:
            raise ValueError(f"unknown direction: {direction!r}")
        out["direction"] = direction
        targets = out.get("target_metric_ids")
        if not isinstance(targets, list) or not targets:
            raise ValueError("revenue_driver requires target_metric_ids")
        out["target_metric_ids"] = sorted({str(t) for t in targets})
        out["reported_or_derived"] = "management_assertion"

    out["_normalizer_version"] = NORMALIZER_VERSION
    return out


def _effective_scale(parsed_scale: int, scale_hint: int | None) -> int:
    """The exponent that describes one field's mantissa.

    A suffix parsed from the field's own text ("$100 million") is authoritative
    for that field; otherwise the payload's declared scale applies, so the two
    can never compound.
    """
    return parsed_scale or (scale_hint or 0)


def _reconcile_scale(mantissas: dict[str, tuple[Decimal, int]]) -> tuple[dict[str, Decimal], int]:
    """Restate every field of one payload against a single shared exponent.

    ``extraction-payload/v1`` carries one ``scale`` for the whole payload, so a
    range whose bounds were written at different magnitudes ("900 million to 1.2
    billion") has to be brought onto a common exponent. The *smallest* exponent
    is chosen, which makes every adjustment a left shift — exact under Decimal,
    never a division, so no bound can be rounded across the other.
    """
    common = min(scale for _mantissa, scale in mantissas.values())
    restated = {
        key: (mantissa.scaleb(scale - common) if scale != common else mantissa)
        for key, (mantissa, scale) in mantissas.items()
    }
    return restated, common


def _normalize_qualifiers(quals: Any) -> dict[str, Any]:
    if quals is None:
        return {}
    if not isinstance(quals, dict):
        raise ValueError("qualifiers must be an object")
    return {str(k): quals[k] for k in sorted(quals, key=str)}


def _normalize_numeric_fields(out: dict[str, Any], *, value_keys: tuple[str, ...]) -> None:
    unit = out.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("unit required for numeric payloads")
    out["unit"] = unit.strip()

    # Never converts currencies, and never infers one from the unit. The
    # blockers are kept out of `blockers` below on purpose: that list gates the
    # declared `scale`, and a missing currency says nothing about the exponent.
    currency, currency_blockers = normalize_currency(currency=out.get("currency"), unit=out["unit"])
    if currency is not None:
        # Assigned only when present, so an absent key stays absent and an
        # explicit null stays null — the schema check grades both.
        out["currency"] = currency

    # Validate the DECLARED exponent before anything uses it. A model-supplied
    # scale=99 or scale=-3 is a wrong-magnitude claim, so it is rejected as a
    # hint and reported as a blocker — never silently honoured, and never
    # raised, because the validate stage is where the pipeline expects blockers.
    # The declared value is left in place so `range_errors` and the schema check
    # see and report it too; nothing multiplies by it, so it cannot inflate a
    # value. The bound lives in `validate/range.py` (single source of truth).
    declared = out.get("scale")
    blockers = scale_blockers(declared)
    scale_hint: int | None = None
    if not blockers and isinstance(declared, int) and not isinstance(declared, bool):
        scale_hint = declared

    mantissas: dict[str, tuple[Decimal, int]] = {}
    for key in value_keys:
        raw = out.get(key)
        if raw is None:
            # Fall back to parsing raw_value once for single-value shapes.
            if len(value_keys) == 1 and isinstance(out.get("raw_value"), str):
                value, parsed_scale, _sign = parse_numeric(out["raw_value"])
                mantissas[key] = (value, _effective_scale(parsed_scale, scale_hint))
                continue
            raise ValueError(f"missing numeric field {key}")
        if isinstance(raw, Decimal):
            mantissas[key] = (raw, _effective_scale(0, scale_hint))
        elif isinstance(raw, str):
            value, parsed_scale, _sign = parse_numeric(raw)
            mantissas[key] = (value, _effective_scale(parsed_scale, scale_hint))
        elif isinstance(raw, int) and not isinstance(raw, bool):
            mantissas[key] = (Decimal(raw), _effective_scale(0, scale_hint))
        else:
            raise ValueError(f"{key} must be a decimal string (got {type(raw).__name__})")

    # The mantissa + exponent pair is the contract's own representation of a
    # scaled amount — its reference fixture for "$100 million" is
    # {"value": "100", "scale": 6} and the schema requires `scale`. Collapsing
    # the pair to base units at scale 0 would contradict the frozen contract
    # (ADR-0001: code conforms to contracts) and would make the value/scale
    # comparison in packages/retrieval/fel_retrieval/verification.py meaningless.
    # XBRL ingestion keeps the exponent the same way: parser.py preserves the ix
    # `scale` attribute into `financial_facts.scale`.
    restated, common_scale = _reconcile_scale(mantissas)
    for key, mantissa in restated.items():
        out[key] = format_decimal(mantissa)
    if not blockers:
        out["scale"] = common_scale

    # Re-normalizing a normalized payload is a no-op: the mantissa carries no
    # suffix of its own, so the declared scale round-trips unchanged.
    blockers.extend(_resolve_sign(out, restated[value_keys[0]]))
    blockers.extend(currency_blockers)
    _record_blockers(out, blockers)


def _record_blockers(out: dict[str, Any], blockers: list[str]) -> None:
    """Merge freshly detected blockers with any the payload already carries.

    Order-preserving and deduplicated so re-normalizing a normalized payload is
    idempotent, while a blocker the first pass found (a sign the normalizer has
    since corrected, so the check can no longer re-fire) is never dropped.
    """
    existing = out.get(NORMALIZER_BLOCKERS_KEY)
    merged: list[str] = []
    for blocker in [*(existing if isinstance(existing, list) else []), *blockers]:
        text = str(blocker)
        if text not in merged:
            merged.append(text)
    if merged:
        out[NORMALIZER_BLOCKERS_KEY] = merged


def _resolve_sign(out: dict[str, Any], primary: Decimal) -> list[str]:
    """Set ``sign`` from the primary value and report a declared sign that disagrees.

    A model-declared ``sign: "positive"`` must never be allowed to stand over a
    value that normalizes negative — that is the loss/profit inversion. The value
    is the authoritative number, so the derived sign wins and the disagreement
    becomes a blocker rather than a silent overwrite.
    """
    derived = "positive" if primary > 0 else "negative" if primary < 0 else "zero"
    declared = out.get("sign")
    out["sign"] = derived
    if declared in {"positive", "negative", "zero"} and declared != derived:
        return [f"sign contradicts value: declared {declared}, value is {derived}"]
    if declared is not None and declared not in {"positive", "negative", "zero"}:
        return [f"sign must be positive/negative/zero: {declared!r}"]
    return []


__all__ = ["normalize_payload"]
