"""Typed fiscal periods (T0401 / Constitution II: explicit fiscal periods).

A period is either a :class:`FiscalQuarter` or a :class:`FiscalYear`. Both are
frozen value objects with a total order *within* their kind; comparing across
kinds raises :class:`PeriodError` because "FY2024" versus "FY2024 Q4" has no
meaningful ordering (the year contains the quarter). Period arithmetic is
integer-based (``shift``) so rollover cannot drift; calendar spans — and the
leap-year day counts that depend on them — live in :class:`FiscalCalendar`,
which is where an issuer's fiscal year-end month enters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import ClassVar

from fel_calculation_engine.errors import PeriodError

_KEY = re.compile(r"^FY(\d{4})(?:Q([1-4]))?$")


class PeriodKind(StrEnum):
    """Granularity of a fiscal period; also the denominator of a per-period rate."""

    QUARTER = "quarter"
    YEAR = "year"


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PeriodError(f"{field} must be an int, got {type(value).__name__}")
    return value


@dataclass(frozen=True, slots=True)
class FiscalPeriod:
    """Common base for typed periods. Do not instantiate directly."""

    kind: ClassVar[PeriodKind]
    fiscal_year: int

    def __post_init__(self) -> None:
        if type(self) is FiscalPeriod:
            raise PeriodError("FiscalPeriod is abstract; use FiscalQuarter or FiscalYear")
        year = _require_int(self.fiscal_year, "fiscal_year")
        if not 1000 <= year <= 9999:
            raise PeriodError(f"fiscal_year must be a four-digit year, got {year}")

    # Ordering is explicit and kind-scoped; subclasses supply ``_ordinal``.
    def _ordinal(self) -> int:
        raise NotImplementedError

    def _same_kind(self, other: object) -> FiscalPeriod:
        if isinstance(other, FiscalPeriod) and type(other) is type(self):
            return other
        raise PeriodError(
            f"cannot order {type(self).__name__} against {type(other).__name__}",
            left=type(self).__name__,
            right=type(other).__name__,
        )

    def __lt__(self, other: object) -> bool:
        return self._ordinal() < self._same_kind(other)._ordinal()

    def __le__(self, other: object) -> bool:
        return self._ordinal() <= self._same_kind(other)._ordinal()

    def __gt__(self, other: object) -> bool:
        return self._ordinal() > self._same_kind(other)._ordinal()

    def __ge__(self, other: object) -> bool:
        return self._ordinal() >= self._same_kind(other)._ordinal()

    def shift(self, steps: int) -> FiscalPeriod:
        raise NotImplementedError

    def key(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FiscalQuarter(FiscalPeriod):
    kind: ClassVar[PeriodKind] = PeriodKind.QUARTER
    quarter: int

    def __post_init__(self) -> None:
        # ``slots=True`` dataclasses rebuild the class, so zero-argument ``super()`` breaks.
        FiscalPeriod.__post_init__(self)
        quarter = _require_int(self.quarter, "quarter")
        if not 1 <= quarter <= 4:
            raise PeriodError(f"quarter must be 1..4, got {quarter}")

    def _ordinal(self) -> int:
        return self.fiscal_year * 4 + (self.quarter - 1)

    @property
    def year(self) -> FiscalYear:
        return FiscalYear(self.fiscal_year)

    def shift(self, steps: int) -> FiscalQuarter:
        ordinal = self._ordinal() + _require_int(steps, "steps")
        fiscal_year, index = divmod(ordinal, 4)
        return FiscalQuarter(fiscal_year, index + 1)

    def next(self) -> FiscalQuarter:
        return self.shift(1)

    def prev(self) -> FiscalQuarter:
        return self.shift(-1)

    def key(self) -> str:
        return f"FY{self.fiscal_year}Q{self.quarter}"


@dataclass(frozen=True, slots=True)
class FiscalYear(FiscalPeriod):
    kind: ClassVar[PeriodKind] = PeriodKind.YEAR

    def _ordinal(self) -> int:
        return self.fiscal_year

    def quarters(self) -> tuple[FiscalQuarter, FiscalQuarter, FiscalQuarter, FiscalQuarter]:
        return (
            FiscalQuarter(self.fiscal_year, 1),
            FiscalQuarter(self.fiscal_year, 2),
            FiscalQuarter(self.fiscal_year, 3),
            FiscalQuarter(self.fiscal_year, 4),
        )

    def shift(self, steps: int) -> FiscalYear:
        return FiscalYear(self.fiscal_year + _require_int(steps, "steps"))

    def key(self) -> str:
        return f"FY{self.fiscal_year}"


def parse_period(text: str) -> FiscalPeriod:
    match = _KEY.fullmatch(text)
    if match is None:
        raise PeriodError(f"not a fiscal period key: {text!r}")
    year = int(match.group(1))
    if match.group(2) is None:
        return FiscalYear(year)
    return FiscalQuarter(year, int(match.group(2)))


def _add_months(first_of_month: date, months: int) -> date:
    year, month0 = divmod(first_of_month.month - 1 + months, 12)
    return date(first_of_month.year + year, month0 + 1, 1)


@dataclass(frozen=True, slots=True)
class FiscalCalendar:
    """Maps typed periods onto calendar dates for an issuer's fiscal year-end month.

    ``FY N`` ends on the last day of ``year_end_month`` in calendar year ``N``.
    Q1 is the first three months of that fiscal year.
    """

    year_end_month: int = 12

    def __post_init__(self) -> None:
        month = _require_int(self.year_end_month, "year_end_month")
        if not 1 <= month <= 12:
            raise PeriodError(f"year_end_month must be 1..12, got {month}")

    def _year_start(self, fiscal_year: int) -> date:
        if self.year_end_month == 12:
            return date(fiscal_year, 1, 1)
        return date(fiscal_year - 1, self.year_end_month + 1, 1)

    def span(self, period: FiscalPeriod) -> tuple[date, date]:
        start = self._year_start(period.fiscal_year)
        if isinstance(period, FiscalQuarter):
            start = _add_months(start, 3 * (period.quarter - 1))
            months = 3
        elif isinstance(period, FiscalYear):
            months = 12
        else:
            raise PeriodError(f"unsupported period type {type(period).__name__}")
        end = _add_months(start, months) - timedelta(days=1)
        return start, end

    def days(self, period: FiscalPeriod) -> int:
        start, end = self.span(period)
        return (end - start).days + 1


__all__ = [
    "FiscalCalendar",
    "FiscalPeriod",
    "FiscalQuarter",
    "FiscalYear",
    "PeriodKind",
    "parse_period",
]
