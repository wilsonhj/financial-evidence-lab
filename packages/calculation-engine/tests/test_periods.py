"""Typed fiscal periods: quarters and years with explicit ordering (T0401 / Constitution II)."""

from __future__ import annotations

from datetime import date

import pytest

from fel_calculation_engine.errors import PeriodError
from fel_calculation_engine.periods import (
    FiscalCalendar,
    FiscalPeriod,
    FiscalQuarter,
    FiscalYear,
    PeriodKind,
    parse_period,
)


def test_quarter_construction_validates_range() -> None:
    q = FiscalQuarter(2024, 3)
    assert q.fiscal_year == 2024 and q.quarter == 3
    assert q.kind is PeriodKind.QUARTER
    for bad in (0, 5, -1):
        with pytest.raises(PeriodError):
            FiscalQuarter(2024, bad)
    with pytest.raises(PeriodError):
        FiscalQuarter(2024, "3")  # type: ignore[arg-type]
    with pytest.raises(PeriodError):
        FiscalQuarter(24, 1)


def test_year_construction_and_kind() -> None:
    y = FiscalYear(2024)
    assert y.kind is PeriodKind.YEAR
    assert y.quarters() == tuple(FiscalQuarter(2024, q) for q in (1, 2, 3, 4))
    assert FiscalQuarter(2024, 2).year == y


def test_quarter_rollover_across_fiscal_year_boundary() -> None:
    assert FiscalQuarter(2024, 4).next() == FiscalQuarter(2025, 1)
    assert FiscalQuarter(2025, 1).prev() == FiscalQuarter(2024, 4)
    assert FiscalQuarter(2024, 2).shift(7) == FiscalQuarter(2026, 1)
    assert FiscalQuarter(2024, 2).shift(-6) == FiscalQuarter(2022, 4)
    assert FiscalYear(2024).shift(3) == FiscalYear(2027)


def test_ordering_is_explicit_within_a_kind_and_refused_across_kinds() -> None:
    assert FiscalQuarter(2024, 4) < FiscalQuarter(2025, 1)
    assert FiscalQuarter(2024, 1) <= FiscalQuarter(2024, 1)
    assert FiscalYear(2023) < FiscalYear(2024)
    assert sorted([FiscalQuarter(2025, 1), FiscalQuarter(2024, 3), FiscalQuarter(2024, 1)]) == [
        FiscalQuarter(2024, 1),
        FiscalQuarter(2024, 3),
        FiscalQuarter(2025, 1),
    ]
    with pytest.raises(PeriodError):
        _ = FiscalQuarter(2024, 4) < FiscalYear(2024)  # type: ignore[operator]
    assert FiscalQuarter(2024, 4) != FiscalYear(2024)


def test_no_string_periods_in_arithmetic() -> None:
    with pytest.raises(PeriodError):
        FiscalQuarter(2024, 1).shift("1")  # type: ignore[arg-type]
    with pytest.raises(PeriodError):
        _ = FiscalQuarter(2024, 1) < "FY2024Q2"  # type: ignore[operator]


def test_canonical_key_round_trips() -> None:
    q = FiscalQuarter(2024, 3)
    assert q.key() == "FY2024Q3"
    assert FiscalYear(2024).key() == "FY2024"
    assert parse_period("FY2024Q3") == q
    assert parse_period("FY2024") == FiscalYear(2024)
    for bad in ("2024Q3", "FY2024Q5", "FY24", "fy2024", "FY2024Q"):
        with pytest.raises(PeriodError):
            parse_period(bad)
    p: FiscalPeriod = q
    assert isinstance(p, FiscalPeriod)


def test_fiscal_calendar_spans_are_leap_year_correct() -> None:
    dec = FiscalCalendar(year_end_month=12)
    assert dec.span(FiscalQuarter(2024, 1)) == (date(2024, 1, 1), date(2024, 3, 31))
    assert dec.span(FiscalYear(2024)) == (date(2024, 1, 1), date(2024, 12, 31))
    assert dec.days(FiscalQuarter(2024, 1)) == 91  # 2024 is a leap year
    assert dec.days(FiscalQuarter(2023, 1)) == 90
    assert dec.days(FiscalYear(2024)) == 366
    assert dec.days(FiscalYear(2100)) == 365  # century rule


def test_fiscal_calendar_with_non_december_year_end() -> None:
    # Fiscal year ends in January (FY2025 = Feb 2024 .. Jan 2025); Q4 contains Feb 29 only
    # when the *calendar* year of February is a leap year.
    jan = FiscalCalendar(year_end_month=1)
    assert jan.span(FiscalYear(2025)) == (date(2024, 2, 1), date(2025, 1, 31))
    assert jan.span(FiscalQuarter(2025, 1)) == (date(2024, 2, 1), date(2024, 4, 30))
    assert jan.days(FiscalQuarter(2025, 1)) == 90
    assert jan.days(FiscalQuarter(2024, 1)) == 89
    with pytest.raises(PeriodError):
        FiscalCalendar(year_end_month=13)
