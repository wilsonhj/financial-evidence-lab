"""Range / scale / Decimal-bound validators."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def check_range(payload: dict[str, Any]) -> list[str]:
    """Guidance range low/high ordering (stable machine codes for callers)."""
    if payload.get("kind") != "guidance" or payload.get("shape") != "range":
        return []
    try:
        low = Decimal(str(payload["low"]))
        high = Decimal(str(payload["high"]))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return ["range_bounds_not_decimal"]
    if low > high:
        return ["range_low_gt_high"]
    return []


def range_errors(payload: dict[str, Any]) -> list[str]:
    """Decimal-field and scale plausibility blockers for the live validate path."""
    errors: list[str] = []
    for key in ("value", "low", "high"):
        if key not in payload:
            continue
        try:
            Decimal(str(payload[key]))
        except (InvalidOperation, TypeError):
            errors.append(f"{key} is not a decimal string")
    scale = payload.get("scale")
    if scale is not None and (not isinstance(scale, int) or isinstance(scale, bool)):
        errors.append("scale must be int")
    elif isinstance(scale, int) and (scale < 0 or scale > 12):
        errors.append(f"scale out of range: {scale}")
    return errors


__all__ = ["check_range", "range_errors"]
