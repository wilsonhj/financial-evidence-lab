"""Normalize extraction-payload proposals with Decimal (retain raw_value)."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from fel_workers.extraction.normalize.numeric import format_decimal, parse_numeric
from fel_workers.extraction.normalize.period import normalize_period
from fel_workers.extraction.types import NORMALIZER_VERSION

_CURRENCY_RE_OK = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
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
    out["dimensions"] = _normalize_dimensions(out.get("dimensions"))
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


def _normalize_dimensions(dims: Any) -> dict[str, str]:
    if dims is None:
        return {}
    if not isinstance(dims, dict):
        raise ValueError("dimensions must be an object")
    return {str(k): str(v) for k, v in sorted(dims.items(), key=lambda kv: str(kv[0]))}


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

    currency = out.get("currency")
    if currency is not None:
        if not isinstance(currency, str) or len(currency) != 3 or set(currency) - _CURRENCY_RE_OK:
            raise ValueError(f"currency must be ISO-4217 alpha-3 or null: {currency!r}")
        out["currency"] = currency.upper()
    # Never convert currencies.

    scale_hint: int | None = None
    if "scale" in out and out["scale"] is not None:
        if not isinstance(out["scale"], int) or isinstance(out["scale"], bool):
            raise ValueError("scale must be an integer")
        scale_hint = out["scale"]

    for key in value_keys:
        raw = out.get(key)
        if raw is None:
            # Fall back to parsing raw_value once for single-value shapes.
            if len(value_keys) == 1 and isinstance(out.get("raw_value"), str):
                value, parsed_scale, sign = parse_numeric(out["raw_value"])
                out[key] = format_decimal(value)
                if scale_hint is None:
                    scale_hint = parsed_scale
                out["sign"] = sign
                continue
            raise ValueError(f"missing numeric field {key}")
        if isinstance(raw, Decimal):
            value = raw
            sign = "positive" if value > 0 else "negative" if value < 0 else "zero"
            out[key] = format_decimal(value)
            out["sign"] = out.get("sign") or sign
        elif isinstance(raw, str):
            value, parsed_scale, sign = parse_numeric(raw)
            out[key] = format_decimal(value)
            if scale_hint is None:
                scale_hint = parsed_scale
            out["sign"] = out.get("sign") or sign
        elif isinstance(raw, int) and not isinstance(raw, bool):
            value = Decimal(raw)
            out[key] = format_decimal(value)
            out["sign"] = out.get("sign") or (
                "positive" if value > 0 else "negative" if value < 0 else "zero"
            )
        else:
            raise ValueError(f"{key} must be a decimal string (got {type(raw).__name__})")

    out["scale"] = 0 if scale_hint is None else scale_hint
    if out.get("sign") not in {"positive", "negative", "zero"}:
        # Derive from primary numeric field.
        primary = Decimal(out[value_keys[0]])
        out["sign"] = "positive" if primary > 0 else "negative" if primary < 0 else "zero"


__all__ = ["normalize_payload"]
