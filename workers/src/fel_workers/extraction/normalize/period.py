"""Period / fiscal-window normalization (Decimal-free; date strings only)."""

from __future__ import annotations

from datetime import date
from typing import Any

_PERIOD_TYPES = frozenset({"instant", "duration", "trailing_window", "forecast"})


def normalize_period(period: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a period object; retain raw fiscal_period text when present."""
    if not isinstance(period, dict):
        raise ValueError("period must be an object")
    ptype = period.get("type")
    if ptype not in _PERIOD_TYPES:
        raise ValueError(f"unknown period.type: {ptype!r}")
    out: dict[str, Any] = {"type": ptype}
    for key in ("instant", "start", "end"):
        if key in period and period[key] is not None:
            out[key] = _normalize_date(str(period[key]))
    if "fiscal_period" in period:
        fp = period["fiscal_period"]
        out["fiscal_period"] = None if fp is None else str(fp).strip() or None
    _validate_shape(out)
    return out


def _normalize_date(value: str) -> str:
    text = value.strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value!r}") from exc


def _validate_shape(period: dict[str, Any]) -> None:
    ptype = period["type"]
    if ptype == "instant" and "instant" not in period:
        raise ValueError("instant period requires instant date")
    if ptype in {"duration", "trailing_window"} and not (period.get("start") and period.get("end")):
        raise ValueError(f"{ptype} period requires start and end")
    if ptype == "forecast" and "end" not in period and "instant" not in period:
        raise ValueError("forecast period requires end or instant")
    start, end = period.get("start"), period.get("end")
    if start and end and start > end:
        raise ValueError("period.start must be <= period.end")


__all__ = ["normalize_period"]
