"""Range / scale / Decimal-bound validators."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

# Plausibility bound on a payload's decimal exponent, and the single source of
# truth for it: `normalize/payload.py` imports these rather than restating the
# numbers, so the normalizer and the validator can never drift apart.
#
# Rationale for the bound: the largest magnitude word a filing uses is
# 'trillion' (10**12), and the contract's own reference fixtures sit at 0, 6 and
# 9. A negative exponent would silently divide a reported figure; anything above
# 12 is not a scale a filing states. The frozen schema types `scale` as an
# unbounded integer, so this is a validator-side plausibility check, not a
# schema claim — a payload outside it is blocked for review, never rewritten.
SCALE_MIN = 0
SCALE_MAX = 12


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
    elif isinstance(scale, int) and (scale < SCALE_MIN or scale > SCALE_MAX):
        errors.append(f"scale out of range: {scale}")
    return errors


def scale_blockers(scale: Any) -> list[str]:
    """Blockers for one declared ``scale``, using the same bound as ``range_errors``.

    Split out so the normalizer can check a model-declared exponent *before*
    carrying it, without restating the bound or duplicating the message text.
    """
    if scale is None:
        return []
    if not isinstance(scale, int) or isinstance(scale, bool):
        return ["scale must be int"]
    if scale < SCALE_MIN or scale > SCALE_MAX:
        return [f"scale out of range: {scale}"]
    return []


__all__ = ["SCALE_MAX", "SCALE_MIN", "check_range", "range_errors", "scale_blockers"]
