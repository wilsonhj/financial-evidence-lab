"""Decimal numeric normalization helpers (no float math)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# The grouped alternative requires at least one ',\d{3}' so it can never win on
# a bare digit run and truncate it ('4200000' -> '420'). The suffix is anchored
# with a word boundary so unit words keep their own meaning ('150 bps' is not
# 150 billion). A parenthesized amount is accounting notation for a negative;
# the closing paren may sit before or after the magnitude suffix.
_NUM_RE = re.compile(
    r"(?P<open>\()?\s*"
    r"(?P<sign>[-+])?\s*"
    r"(?P<body>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    r"(?P<close_bare>\s*\))?"
    r"(?:\s*(?P<suffix>million|billion|thousand|[mbk])s?\b)?"
    r"(?P<close_suffixed>\s*\))?",
    re.IGNORECASE,
)

_SCALE_SUFFIX = {
    "k": 3,
    "thousand": 3,
    "m": 6,
    "million": 6,
    "b": 9,
    "billion": 9,
}


def preview_normalize(raw_value: str, *, unit: str | None = None) -> dict[str, Any]:
    """Best-effort preview used by allowlisted tools — never authoritative float."""
    try:
        value, scale, sign = parse_numeric(raw_value)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "value": format(value, "f"),
        "scale": scale,
        "sign": sign,
        "unit": unit,
        "raw_value": raw_value,
    }


def parse_numeric(raw_value: str) -> tuple[Decimal, int, str]:
    """Parse raw numeric text into (value, scale, sign). Keeps Decimal only.

    ``value`` is the mantissa as written and ``scale`` the magnitude suffix
    that still has to be applied to reach base units; ``normalize_payload``
    applies it exactly once.
    """
    if not raw_value or not isinstance(raw_value, str):
        raise ValueError("raw_value required")
    cleaned = raw_value.replace("$", "").replace("%", "").strip()
    match = _NUM_RE.search(cleaned)
    if match is None:
        raise ValueError(f"no numeric token in raw_value: {raw_value!r}")
    body = match.group("body").replace(",", "")
    try:
        value = Decimal(body)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {body!r}") from exc
    scale = 0
    suffix = match.group("suffix")
    if suffix:
        scale = _SCALE_SUFFIX[suffix.lower()]
    explicit_sign = match.group("sign")
    parenthesized = match.group("open") is not None and (
        match.group("close_bare") is not None or match.group("close_suffixed") is not None
    )
    if explicit_sign == "-" or parenthesized:
        value = -abs(value)
    elif explicit_sign == "+":
        value = abs(value)
    if value > 0:
        sign = "positive"
    elif value < 0:
        sign = "negative"
    else:
        sign = "zero"
    return value, scale, sign


def format_decimal(value: Decimal) -> str:
    """Normalize Decimal to a contract decimal-string (no exponent, no float)."""
    normalized = value.normalize() if value != 0 else Decimal("0")
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


__all__ = ["format_decimal", "parse_numeric", "preview_normalize"]
