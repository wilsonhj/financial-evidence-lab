"""Typed canonical JSON for content addressing (T0402 / T0403 — issue #63 checklist)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fel_calculation_engine.canonical import CanonicalizationError, canonical_json, content_hash
from fel_calculation_engine.periods import PeriodKind
from fel_calculation_engine.units import Unit, UnitKind, currency
from fel_calculation_engine.values import CALC_CONTEXT, canonical_decimal, require_decimal


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


def test_canonical_decimal_is_injective_at_full_engine_precision() -> None:
    """Two distinct engine outputs must not share a content address.

    ``canonical_decimal`` used a bare ``value.normalize()``, which runs in the
    *ambient* decimal context. Its default precision is 28, four digits short of
    the 34 this engine computes at, so the encoder silently rounded results
    before they were hashed: ``divide(1, 3)`` and that value plus ``1E-34`` are
    unequal, both pass ``require_decimal``, and both encoded to the same
    28-digit string. Content addressing is how provenance is established, so a
    non-injective encoder is a correctness defect, not a formatting one.

    Revert the ``context=CALC_CONTEXT`` argument and this test fails.
    """
    a = CALC_CONTEXT.divide(Decimal(1), Decimal(3))
    b = CALC_CONTEXT.add(a, Decimal("1E-34"))

    assert a != b
    assert len(a.as_tuple().digits) == CALC_CONTEXT.prec
    require_decimal(a, "a")
    require_decimal(b, "b")

    assert canonical_decimal(a) != canonical_decimal(
        b
    ), "two distinct engine-produced values share one canonical encoding"
    # The full precision survives rather than being rounded away.
    assert canonical_decimal(a).endswith("3333")
    assert canonical_decimal(b).endswith("3334")


def test_canonical_decimal_still_collapses_value_equal_forms() -> None:
    """The intended collapsing is untouched: equal values keep one encoding."""
    for left, right in (("1.5", "1.50"), ("0", "-0"), ("1E+2", "100"), ("0.100", "0.1")):
        first, second = Decimal(left), Decimal(right)
        assert first == second
        assert canonical_decimal(first) == canonical_decimal(second)
    assert "E" not in canonical_decimal(Decimal("1E+30"))


def test_canonicalizer_refuses_over_precision_rather_than_rounding_it_away() -> None:
    """`canonical_json` and `content_hash` are public; they must not trust callers.

    `canonical_decimal` is exact only within ``CALC_CONTEXT.prec``. Beyond it
    ``normalize`` rounds, so two unequal Decimals encode identically — before
    this guard, ``1.0…01`` and ``1.0…02`` at 42 digits both became ``"1"`` and
    ``content_hash`` collided. Every value arriving through a node has passed
    ``require_decimal``, which rejects that shape; these two entry points had
    only an ``is_finite`` check, so injectivity held by caller discipline rather
    than by construction.
    """
    over = Decimal("1." + "0" * 40 + "1")
    twin = Decimal("1." + "0" * 40 + "2")
    assert over != twin
    assert len(over.as_tuple().digits) > CALC_CONTEXT.prec

    for value in (over, twin):
        with pytest.raises(CanonicalizationError, match="significant digits"):
            canonical_json(value)
        with pytest.raises(CanonicalizationError, match="significant digits"):
            content_hash(value)

    # Exactly at the precision is still accepted: the bound is the engine's own.
    at_limit = CALC_CONTEXT.divide(Decimal(1), Decimal(3))
    assert len(at_limit.as_tuple().digits) == CALC_CONTEXT.prec
    assert canonical_json(at_limit)


def test_canonicalizer_refuses_an_exponent_it_would_have_to_expand() -> None:
    """A financial quantity does not carry a 10^6 exponent, and expanding one hurts.

    ``1E+999999`` encoded to just over a million characters — hashed once per
    snapshot and again per result id — and ``1E+1000000`` raised an untyped
    ``decimal.Overflow`` that escapes ``except CalculationEngineError``, the same
    class of leak as the recursive cycle reporter.
    """
    for literal in ("1E+999999", "1E+1000000", "1E-999999"):
        with pytest.raises(CanonicalizationError, match="exponent"):
            canonical_json(Decimal(literal))

    # Ordinary magnitudes are untouched.
    for literal in ("0", "1.5", "-0", "1E+2", "1E-20", "123456789.123456789"):
        assert canonical_json(Decimal(literal))
