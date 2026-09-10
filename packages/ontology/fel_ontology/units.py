"""Comparison-only unit vocabulary, pinned by ADR-0019.

Never rewrite source payloads or infer their separate declared currency.
Unknown issuer units preserve case, interior whitespace and Unicode.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

UNIT_POLICY_VERSION = "unit-comparison/v1"
_CURRENCY_CODES = frozenset(
    json.loads(files("fel_ontology").joinpath("data/currency-codes.json").read_text())["codes"]
)
_ALIASES = {
    u: u
    for u in (
        "count",
        "currency",
        "pure",
        "ratio",
        "shares",
        "customers",
        "percent",
        "percentage_points",
    )
}
_ALIASES.update(
    {"%": "percent", "pct": "percent", "percentage": "percent", "pp": "percentage_points"}
)


def canonical_unit(value: Any) -> Any:
    """Canonicalize only explicitly supported ASCII aliases; preserve invalid types."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    numerator, slash, suffix = text.partition("/")
    if numerator.isascii():
        upper = numerator.upper()
        if upper in _CURRENCY_CODES:
            return upper + slash + suffix
        lower = numerator.lower()
        if lower == "currency":
            return lower + slash + suffix
        if not slash and lower in _ALIASES:
            return _ALIASES[lower]
    return text


def is_monetary_unit(value: Any) -> bool:
    unit = canonical_unit(value)
    if not isinstance(unit, str):
        return False
    numerator = unit.partition("/")[0]
    return numerator == "currency" or numerator in _CURRENCY_CODES
