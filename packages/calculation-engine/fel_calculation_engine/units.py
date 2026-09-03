"""Typed units with a closed, fail-closed algebra (T0401 / T0403, FR-MOD-002).

Four unit kinds: ``CURRENCY`` (with an ISO 4217 code), ``COUNT``, ``PERCENT``
and ``RATIO``. Any unit may additionally be a *rate* ``per`` a fiscal period
kind (``USD per quarter``). The algebra below is the complete table; every
combination not listed raises :class:`UnitError`.

Percent is a presentation form (``60`` means 60 %). It only ever adds to or
subtracts from another percent; multiplying or dividing by a percent raises so
that the ``60 * revenue`` mistake is impossible — normalize to a ``RATIO``
first (see :meth:`fel_calculation_engine.values.Quantity.to_ratio`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from fel_calculation_engine.errors import UnitError
from fel_calculation_engine.periods import PeriodKind

_ISO_4217 = re.compile(r"^[A-Z]{3}$")


class UnitKind(StrEnum):
    CURRENCY = "currency"
    COUNT = "count"
    PERCENT = "percent"
    RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class Unit:
    kind: UnitKind
    currency: str | None = None
    per_period: PeriodKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, UnitKind):
            raise UnitError(f"unit kind must be UnitKind, got {self.kind!r}")
        if self.kind is UnitKind.CURRENCY:
            if self.currency is None or not _ISO_4217.fullmatch(self.currency):
                raise UnitError(
                    f"currency unit requires an ISO 4217 code, got {self.currency!r}",
                    currency=self.currency,
                )
        elif self.currency is not None:
            raise UnitError(f"{self.kind.value} unit must not carry a currency code")
        if self.per_period is not None and not isinstance(self.per_period, PeriodKind):
            raise UnitError(f"per_period must be PeriodKind, got {self.per_period!r}")

    # -- construction helpers -------------------------------------------------

    def per(self, period_kind: PeriodKind) -> Unit:
        """Turn a stock unit into a rate per fiscal period kind."""
        if self.per_period is not None:
            raise UnitError(f"{self.key()} is already a per-period rate")
        return Unit(kind=self.kind, currency=self.currency, per_period=period_kind)

    def stock(self) -> Unit:
        """Drop the per-period denominator."""
        return Unit(kind=self.kind, currency=self.currency)

    @property
    def is_rate(self) -> bool:
        return self.per_period is not None

    # -- canonical encoding -----------------------------------------------------

    def key(self) -> str:
        base = self.kind.value
        if self.kind is UnitKind.CURRENCY:
            base = f"{base}:{self.currency}"
        return base if self.per_period is None else f"{base}/{self.per_period.value}"

    @classmethod
    def parse(cls, key: str) -> Unit:
        base, _, per = key.partition("/")
        kind_text, _, code = base.partition(":")
        try:
            kind = UnitKind(kind_text)
        except ValueError as exc:
            raise UnitError(f"unknown unit kind in {key!r}") from exc
        per_period: PeriodKind | None = None
        if per:
            try:
                per_period = PeriodKind(per)
            except ValueError as exc:
                raise UnitError(f"unknown period kind in {key!r}") from exc
        return cls(kind=kind, currency=code or None, per_period=per_period)

    # -- algebra ------------------------------------------------------------------

    def add(self, other: Unit) -> Unit:
        if self != other:
            raise UnitError(
                f"cannot add {self.key()} and {other.key()}", left=self.key(), right=other.key()
            )
        return self

    def sub(self, other: Unit) -> Unit:
        if self != other:
            raise UnitError(
                f"cannot subtract {other.key()} from {self.key()}",
                left=self.key(),
                right=other.key(),
            )
        return self

    def mul(self, other: Unit) -> Unit:
        if UnitKind.PERCENT in (self.kind, other.kind):
            raise UnitError(
                f"percent must be normalized to a ratio before multiplying: "
                f"{self.key()} * {other.key()}"
            )
        if self.per_period is not None and other.per_period is not None:
            raise UnitError(f"cannot multiply two rates: {self.key()} * {other.key()}")
        per_period = self.per_period or other.per_period
        if self.kind is UnitKind.RATIO:
            return Unit(kind=other.kind, currency=other.currency, per_period=per_period)
        if other.kind is UnitKind.RATIO:
            return Unit(kind=self.kind, currency=self.currency, per_period=per_period)
        kinds = {self.kind, other.kind}
        if kinds == {UnitKind.CURRENCY, UnitKind.COUNT}:
            code = self.currency if self.kind is UnitKind.CURRENCY else other.currency
            return Unit(kind=UnitKind.CURRENCY, currency=code, per_period=per_period)
        raise UnitError(f"no unit for {self.key()} * {other.key()}")

    def div(self, other: Unit) -> Unit:
        if UnitKind.PERCENT in (self.kind, other.kind):
            raise UnitError(
                f"percent must be normalized to a ratio before dividing: "
                f"{self.key()} / {other.key()}"
            )
        if other.per_period is not None:
            if self.per_period != other.per_period:
                raise UnitError(f"rate denominators differ: {self.key()} / {other.key()}")
            per_period: PeriodKind | None = None
        else:
            per_period = self.per_period
        if other.kind is UnitKind.RATIO:
            return Unit(kind=self.kind, currency=self.currency, per_period=per_period)
        if self.kind is UnitKind.CURRENCY and other.kind is UnitKind.CURRENCY:
            if self.currency != other.currency:
                raise UnitError(f"cross-currency division: {self.key()} / {other.key()}")
            return Unit(kind=UnitKind.RATIO, per_period=per_period)
        if self.kind is UnitKind.CURRENCY and other.kind is UnitKind.COUNT:
            return Unit(kind=UnitKind.CURRENCY, currency=self.currency, per_period=per_period)
        if self.kind is UnitKind.COUNT and other.kind is UnitKind.COUNT:
            return Unit(kind=UnitKind.RATIO, per_period=per_period)
        raise UnitError(f"no unit for {self.key()} / {other.key()}")


def currency(code: str) -> Unit:
    return Unit(kind=UnitKind.CURRENCY, currency=code)


COUNT = Unit(kind=UnitKind.COUNT)
PERCENT = Unit(kind=UnitKind.PERCENT)
RATIO = Unit(kind=UnitKind.RATIO)

__all__ = ["COUNT", "PERCENT", "RATIO", "Unit", "UnitKind", "currency"]
