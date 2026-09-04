"""Typed units: construction, identity, and fail-closed unit algebra (T0401 / FR-MOD-002).

Unit algebra is a closed table. Anything outside the table raises ``UnitError``
rather than producing a quietly dimensionless number. Percent is a presentation
form: it never multiplies or divides anything until it is normalized to a ratio.
"""

from __future__ import annotations

import pytest

from fel_calculation_engine.errors import UnitError
from fel_calculation_engine.periods import PeriodKind
from fel_calculation_engine.units import COUNT, PERCENT, RATIO, Unit, UnitKind, currency


def test_currency_unit_requires_iso_4217_code() -> None:
    usd = currency("USD")
    assert usd.kind is UnitKind.CURRENCY
    assert usd.currency == "USD"
    with pytest.raises(UnitError):
        currency("usd")
    with pytest.raises(UnitError):
        currency("US")
    with pytest.raises(UnitError):
        Unit(kind=UnitKind.CURRENCY, currency=None)


def test_non_currency_units_reject_currency_code() -> None:
    with pytest.raises(UnitError):
        Unit(kind=UnitKind.COUNT, currency="USD")


def test_units_are_frozen_and_hashable() -> None:
    usd = currency("USD")
    with pytest.raises(AttributeError):
        usd.currency = "EUR"  # type: ignore[misc]
    assert {usd, currency("USD")} == {usd}
    assert currency("USD") != currency("EUR")


def test_add_and_sub_require_identical_units() -> None:
    usd = currency("USD")
    assert usd.add(usd) == usd
    assert usd.sub(usd) == usd
    with pytest.raises(UnitError):
        usd.add(currency("EUR"))
    with pytest.raises(UnitError):
        usd.add(COUNT)
    with pytest.raises(UnitError):
        PERCENT.add(RATIO)
    with pytest.raises(UnitError):
        usd.add(usd.per(PeriodKind.QUARTER))


def test_ratio_is_the_dimensionless_scalar() -> None:
    usd = currency("USD")
    assert usd.mul(RATIO) == usd
    assert RATIO.mul(usd) == usd
    assert COUNT.mul(RATIO) == COUNT
    assert RATIO.mul(RATIO) == RATIO
    assert usd.div(RATIO) == usd
    assert RATIO.div(RATIO) == RATIO


def test_price_times_volume_is_currency() -> None:
    usd = currency("USD")
    assert usd.mul(COUNT) == usd
    assert COUNT.mul(usd) == usd


def test_same_currency_division_is_ratio_and_cross_currency_raises() -> None:
    usd = currency("USD")
    assert usd.div(usd) == RATIO
    assert COUNT.div(COUNT) == RATIO
    with pytest.raises(UnitError):
        usd.div(currency("EUR"))
    with pytest.raises(UnitError):
        usd.mul(currency("EUR"))
    with pytest.raises(UnitError):
        usd.mul(usd)


def test_currency_per_count_is_currency() -> None:
    usd = currency("USD")
    assert usd.div(COUNT) == usd  # ARPU-style: dollars per customer stays a currency amount
    with pytest.raises(UnitError):
        COUNT.div(usd)
    with pytest.raises(UnitError):
        RATIO.div(usd)
    with pytest.raises(UnitError):
        COUNT.mul(COUNT)


def test_percent_never_enters_multiplication_or_division() -> None:
    usd = currency("USD")
    for other in (usd, COUNT, RATIO, PERCENT):
        with pytest.raises(UnitError):
            PERCENT.mul(other)
        with pytest.raises(UnitError):
            other.mul(PERCENT)
        with pytest.raises(UnitError):
            PERCENT.div(other)
        with pytest.raises(UnitError):
            other.div(PERCENT)
    assert PERCENT.add(PERCENT) == PERCENT


def test_per_period_rates_compose_but_never_stack() -> None:
    usd = currency("USD")
    usd_q = usd.per(PeriodKind.QUARTER)
    assert usd_q.per_period is PeriodKind.QUARTER
    assert usd_q.mul(RATIO) == usd_q
    assert COUNT.per(PeriodKind.QUARTER).mul(usd) == usd_q
    assert usd_q.div(usd_q) == RATIO
    assert usd_q.div(COUNT) == usd_q
    with pytest.raises(UnitError):
        usd_q.mul(COUNT.per(PeriodKind.QUARTER))
    with pytest.raises(UnitError):
        usd_q.div(usd.per(PeriodKind.YEAR))
    with pytest.raises(UnitError):
        usd.div(usd_q)
    with pytest.raises(UnitError):
        usd_q.per(PeriodKind.YEAR)


def test_unit_canonical_key_is_stable_and_injective_over_none() -> None:
    usd = currency("USD")
    assert usd.key() == "currency:USD"
    assert COUNT.key() == "count"
    assert usd.per(PeriodKind.YEAR).key() == "currency:USD/year"
    assert RATIO.key() != PERCENT.key()
    assert Unit.parse(usd.per(PeriodKind.YEAR).key()) == usd.per(PeriodKind.YEAR)
    with pytest.raises(UnitError):
        Unit.parse("currency:usd")
    with pytest.raises(UnitError):
        Unit.parse("currency:None")
