"""Currency identification only — no FX conversion (M3-NRM-003)."""

from __future__ import annotations

import re

_CCY = re.compile(r"^[A-Z]{3}$")


def identify_currency(
    *,
    currency: str | None,
    unit: str | None,
    monetary: bool,
) -> tuple[str | None, list[str]]:
    """Identify currency; never convert. Missing monetary currency → blocker."""
    blockers: list[str] = []
    identified = currency
    if identified is None and unit and _CCY.fullmatch(unit):
        identified = unit
    if identified is not None and not _CCY.fullmatch(identified):
        blockers.append("currency_invalid")
        identified = None
    if monetary and identified is None:
        blockers.append("currency_missing_for_monetary")
    return identified, blockers


def is_monetary_unit(unit: str | None) -> bool:
    if not unit:
        return False
    return unit.upper() in {"USD", "EUR", "GBP", "CAD", "AUD", "JPY"} or unit == "currency"


__all__ = ["identify_currency", "is_monetary_unit"]
