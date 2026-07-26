"""Decimal normalization property-style tests (M3-105)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_workers.extraction.normalize import format_decimal, normalize_payload, parse_numeric


@pytest.mark.parametrize(
    ("raw", "expected_value", "expected_scale", "expected_sign"),
    [
        ("$100 million", Decimal("100"), 6, "positive"),
        ("(1,234.50)", Decimal("1234.50"), 0, "positive"),  # paren not negative in parser
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
    assert out["value"] == "100"
    assert out["dimensions"] == {"segment": "total"}
    # No float contamination
    assert Decimal(out["value"]) == Decimal("100")
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
