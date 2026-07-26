"""Range ordering validators (guidance low/high)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def check_range(payload: dict[str, Any]) -> list[str]:
    if payload.get("kind") != "guidance" or payload.get("shape") != "range":
        return []
    try:
        low = Decimal(str(payload["low"]))
        high = Decimal(str(payload["high"]))
    except Exception:  # noqa: BLE001
        return ["range_bounds_not_decimal"]
    if low > high:
        return ["range_low_gt_high"]
    return []


__all__ = ["check_range"]
