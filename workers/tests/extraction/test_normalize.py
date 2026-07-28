"""Decimal normalization property-style tests (M3-105)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_workers.extraction.normalize import format_decimal, normalize_payload, parse_numeric


@pytest.mark.parametrize(
    ("raw", "expected_value", "expected_scale", "expected_sign"),
    [
        ("$100 million", Decimal("100"), 6, "positive"),
        # Accounting notation: a parenthesized amount is a reported NEGATIVE.
        ("(1,234.50)", Decimal("-1234.50"), 0, "negative"),
        ("-2.5%", Decimal("-2.5"), 0, "negative"),
        ("+$3.0 billion", Decimal("3.0"), 9, "positive"),
        ("0", Decimal("0"), 0, "zero"),
    ],
)
def test_parse_numeric_cases(
    raw: str, expected_value: Decimal, expected_scale: int, expected_sign: str
) -> None:
    value, scale, sign = parse_numeric(raw)
    assert value == expected_value
    assert scale == expected_scale
    assert sign == expected_sign
    assert isinstance(value, Decimal)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Unseparated digit runs must never be truncated to their first 3 digits.
        ("4200000", Decimal("4200000")),
        ("12345.67", Decimal("12345.67")),
        ("-1234", Decimal("-1234")),
        ("1,234,567", Decimal("1234567")),
        ("$1,234.50", Decimal("1234.50")),
        ("0.5", Decimal("0.5")),
        (".5", Decimal("0.5")),
        ("999", Decimal("999")),
    ],
)
def test_parse_numeric_keeps_full_magnitude(raw: str, expected: Decimal) -> None:
    value, _scale, _sign = parse_numeric(raw)
    assert value == expected


@pytest.mark.parametrize(
    ("raw", "expected_scale"),
    [
        # Magnitude suffixes only: never the first letter of an unrelated unit.
        ("150 bps", 0),
        ("12 months", 0),
        ("45 basis points", 0),
        ("$100 million", 6),
        ("$100 millions", 6),
        ("$5m", 6),
        ("3.0 billion", 9),
        ("1.2k", 3),
        ("$4,200 thousand", 3),
    ],
)
def test_parse_numeric_suffix_is_anchored(raw: str, expected_scale: int) -> None:
    _value, scale, _sign = parse_numeric(raw)
    assert scale == expected_scale


def test_parse_numeric_parenthesized_is_negative() -> None:
    value, scale, sign = parse_numeric("(1,234.50)")
    assert value == Decimal("-1234.50")
    assert scale == 0
    assert sign == "negative"
    # Suffix survives the accounting parens.
    assert parse_numeric("$(2,500) thousand") == (Decimal("-2500"), 3, "negative")


def test_normalize_payload_applies_scale_to_base_units() -> None:
    raw = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$4.2 million",
        "value": "4.2",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
    }
    out = normalize_payload(raw)
    # Base-currency units (M3-SCH-002); the multiplier is consumed, so scale is 0.
    assert out["value"] == "4200000"
    assert out["scale"] == 0
    assert out["raw_value"] == "$4.2 million"


def test_normalize_payload_applies_scale_from_raw_value_suffix() -> None:
    raw = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "unit": "USD",
        "currency": "USD",
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
    }
    out = normalize_payload(raw)
    assert out["value"] == "100000000"
    assert out["scale"] == 0


def test_normalize_payload_scale_is_idempotent() -> None:
    raw = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "value": "100",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
    }
    once = normalize_payload(raw)
    twice = normalize_payload(once)
    assert once["value"] == twice["value"] == "100000000"
    assert twice["scale"] == 0


def test_normalize_payload_scales_guidance_range_bounds() -> None:
    raw = {
        "schema_version": "extraction-payload/v1",
        "kind": "guidance",
        "shape": "range",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$1.0 billion to $1.2 billion",
        "low": "1.0",
        "high": "1.2",
        "unit": "USD",
        "currency": "USD",
        "scale": 9,
        "sign": "positive",
        "period": {"type": "forecast", "start": "2026-07-01", "end": "2027-06-30"},
        "dimensions": {},
        "qualifiers": {},
    }
    out = normalize_payload(raw)
    assert out["low"] == "1000000000"
    assert out["high"] == "1200000000"
    assert out["scale"] == 0


def test_normalize_payload_retains_raw_and_decimal_strings() -> None:
    raw = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "value": "100",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {"segment": "total"},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
    }
    out = normalize_payload(raw)
    assert out["raw_value"] == "$100 million"
    # scale 6 is applied: normalized values are base-currency units.
    assert out["value"] == "100000000"
    assert out["dimensions"] == {"segment": "total"}
    # No float contamination
    assert Decimal(out["value"]) == Decimal("100000000")
    assert format_decimal(Decimal("100.00")) == "100"


def test_normalize_rejects_floatish_types() -> None:
    raw = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example",
        "metric_id": "arr",
        "raw_value": "1.5",
        "value": 1.5,  # float forbidden
        "unit": "USD",
        "scale": 0,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {},
        "reported_or_derived": "reported",
    }
    with pytest.raises(ValueError):
        normalize_payload(raw)
