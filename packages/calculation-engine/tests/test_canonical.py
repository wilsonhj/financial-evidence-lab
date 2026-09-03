"""Typed canonical JSON for content addressing (T0402 / T0403 — issue #63 checklist)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fel_calculation_engine.canonical import CanonicalizationError, canonical_json, content_hash
from fel_calculation_engine.periods import PeriodKind
from fel_calculation_engine.units import Unit, UnitKind, currency


def test_canonical_json_sorts_keys_and_has_no_whitespace() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_decimals_are_typed_and_representation_independent() -> None:
    assert canonical_json(Decimal("1.50")) == canonical_json(Decimal("1.5"))
    assert canonical_json(Decimal("1.5")) == '{"$decimal":"1.5"}'
    assert canonical_json(Decimal("1.5")) != canonical_json("1.5")
    assert canonical_json(Decimal("1")) != canonical_json(1)


def test_floats_are_rejected_not_stringified() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json(1.5)
    with pytest.raises(CanonicalizationError):
        canonical_json({"x": [1.0]})


def test_datetimes_are_utc_normalized_and_naive_rejected() -> None:
    plus_two = datetime(2024, 5, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert canonical_json(plus_two) == canonical_json(datetime(2024, 5, 1, 12, 0, tzinfo=UTC))
    assert canonical_json(date(2024, 5, 1)) == '{"$date":"2024-05-01"}'
    with pytest.raises(CanonicalizationError):
        canonical_json(datetime(2024, 5, 1))


def test_none_is_json_null_never_a_sentinel_string() -> None:
    assert canonical_json(None) == "null"
    assert canonical_json({"currency": None}) != canonical_json({"currency": "None"})
    assert canonical_json({"currency": None}) != canonical_json({"currency": "-"})
    assert canonical_json({"currency": None}) != canonical_json({"currency": ""})


def test_reserved_keys_cannot_be_forged_from_user_dicts() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({"$decimal": "1.5"})
    with pytest.raises(CanonicalizationError):
        canonical_json({"nested": {"$type": "Unit"}})


def test_dataclasses_enums_and_tuples_encode_structurally() -> None:
    usd_year = currency("USD").per(PeriodKind.YEAR)
    encoded = canonical_json(usd_year)
    assert encoded == '{"$type":"Unit","currency":"USD","kind":"currency","per_period":"year"}'
    assert canonical_json(Unit(kind=UnitKind.COUNT)) == (
        '{"$type":"Unit","currency":null,"kind":"count","per_period":null}'
    )
    assert canonical_json((1, 2)) == canonical_json([1, 2])

    @dataclass(frozen=True)
    class Other:
        currency: str | None = "USD"
        kind: str = "currency"
        per_period: str | None = None

    assert canonical_json(Other()) != canonical_json(currency("USD"))


def test_unsupported_types_are_rejected() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json(object())
    with pytest.raises(CanonicalizationError):
        canonical_json({1: "int keys are ambiguous"})
    with pytest.raises(CanonicalizationError):
        canonical_json({"s": {"a", "b"}})


def test_content_hash_is_sha256_over_canonical_bytes() -> None:
    digest = content_hash({"a": Decimal("1")})
    assert digest.startswith("sha256:") and len(digest) == 7 + 64
    assert digest == content_hash({"a": Decimal("1.0")})
    assert digest != content_hash({"a": Decimal("1.1")})


def test_delimiter_forgery_cannot_collide() -> None:
    # A string join would make these identical; structural encoding cannot.
    assert content_hash(["a|b", "c"]) != content_hash(["a", "b|c"])
    assert content_hash({"x": "a", "y": "b"}) != content_hash({"x": "a,y=b", "y": ""})
    assert content_hash(["ab", "c"]) != content_hash(["a", "bc"])
    assert content_hash({"k": ["a", "b"]}) != content_hash({"k": ["a;b"]})
