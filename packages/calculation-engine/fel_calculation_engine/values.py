"""Decimal-only quantities and exactly-one-lineage provenance (T0401 / T0403).

Constitution II: authoritative math is decimal, typed-unit and deterministic.
``require_decimal`` is the single gate every value passes through — floats,
ints, strings and non-finite Decimals (``NaN``/``Infinity``) are all rejected,
because a NaN passes ``<= 0`` sign checks silently and an Infinity survives
until a quantize far from where it was introduced.

Arithmetic runs under :data:`CALC_CONTEXT` (34 significant digits, banker's
rounding, every inexact-or-invalid condition trapped) so that a division by
zero or an overflow raises :class:`FormulaError` instead of producing a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)
from enum import StrEnum

from fel_calculation_engine.errors import (
    CalculationEngineError,
    FormulaError,
    LineageError,
    UnitError,
    ValueTypeError,
)
from fel_calculation_engine.units import PERCENT, RATIO, Unit, UnitKind

#: IEEE 754 decimal128 precision; wide enough that sums and products of
#: filing-scale values (≤ 10^18 at ≤ 6 decimal places) stay exact.
CALC_CONTEXT = Context(
    prec=34,
    rounding=ROUND_HALF_EVEN,
    traps=[DivisionByZero, InvalidOperation, Overflow],
)

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_HUNDRED = Decimal("100")


def require_safe_id(
    value: object, field: str, error: type[CalculationEngineError] = ValueTypeError
) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise error(f"{field} must match {SAFE_ID.pattern!r}, got {value!r}", field=field)
    return value


def require_decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueTypeError(f"{field} must be a Decimal, got {type(value).__name__}", field=field)
    if not value.is_finite():
        raise ValueTypeError(f"{field} must be finite, got {value}", field=field)
    return value


def canonical_decimal(value: Decimal) -> str:
    """One string per numeric value: ``1.50``, ``1.5`` and ``15E-1`` all encode as ``1.5``."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "0") else text


class Provenance(StrEnum):
    """Constitution II four-way split: reported / user-supplied / derived / forecast."""

    REPORTED = "reported"
    ASSUMPTION = "assumption"
    DERIVED = "derived"
    FORECAST = "forecast"


@dataclass(frozen=True, slots=True)
class Lineage:
    """Exactly one lineage field, selected by provenance kind — never by an or-chain."""

    provenance: Provenance
    source_span_id: str | None = None
    assumption_id: str | None = None
    forecast_run_id: str | None = None
    derived_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            raise LineageError(f"provenance must be Provenance, got {self.provenance!r}")
        present = (
            self.source_span_id is not None,
            self.assumption_id is not None,
            self.forecast_run_id is not None,
            bool(self.derived_from),
        )
        expected = {
            Provenance.REPORTED: (True, False, False, False),
            Provenance.ASSUMPTION: (False, True, False, False),
            Provenance.FORECAST: (False, False, True, False),
            Provenance.DERIVED: (False, False, False, True),
        }[self.provenance]
        if present != expected:
            raise LineageError(
                f"{self.provenance.value} lineage must carry exactly its own lineage field",
                provenance=self.provenance.value,
            )
        for lineage_id in (self.source_span_id, self.assumption_id, self.forecast_run_id):
            if lineage_id is not None:
                require_safe_id(lineage_id, "lineage id", LineageError)
        if not isinstance(self.derived_from, tuple):
            raise LineageError("derived_from must be a tuple of result ids")
        for parent in self.derived_from:
            require_safe_id(parent, "derived_from id", LineageError)
        if len(set(self.derived_from)) != len(self.derived_from):
            raise LineageError("derived_from must not repeat a parent")

    def identity(self) -> tuple[str, ...]:
        """Canonical, order-independent identity fragment for content addressing."""
        if self.provenance is Provenance.DERIVED:
            return (self.provenance.value, *sorted(self.derived_from))
        single = {
            Provenance.REPORTED: self.source_span_id,
            Provenance.ASSUMPTION: self.assumption_id,
            Provenance.FORECAST: self.forecast_run_id,
        }[self.provenance]
        if single is None:  # unreachable after __post_init__; kept explicit for mypy
            raise LineageError("lineage id missing")
        return (self.provenance.value, single)


def _operate(op: str, left: Decimal, right: Decimal) -> Decimal:
    try:
        if op == "add":
            return CALC_CONTEXT.add(left, right)
        if op == "sub":
            return CALC_CONTEXT.subtract(left, right)
        if op == "mul":
            return CALC_CONTEXT.multiply(left, right)
        return CALC_CONTEXT.divide(left, right)
    except (DivisionByZero, InvalidOperation, Overflow) as exc:
        raise FormulaError(
            f"{op} could not be completed exactly: {type(exc).__name__}", operation=op
        ) from exc


@dataclass(frozen=True, slots=True)
class Quantity:
    """A finite Decimal with a typed unit. Arithmetic composes value and unit together."""

    value: Decimal
    unit: Unit

    def __post_init__(self) -> None:
        require_decimal(self.value, "Quantity.value")
        if not isinstance(self.unit, Unit):
            raise UnitError(f"Quantity.unit must be Unit, got {type(self.unit).__name__}")

    @staticmethod
    def _other(other: object) -> Quantity:
        if not isinstance(other, Quantity):
            raise ValueTypeError(
                f"operands must be Quantity, got {type(other).__name__}", field="operand"
            )
        return other

    def __add__(self, other: object) -> Quantity:
        rhs = self._other(other)
        return Quantity(_operate("add", self.value, rhs.value), self.unit.add(rhs.unit))

    def __sub__(self, other: object) -> Quantity:
        rhs = self._other(other)
        return Quantity(_operate("sub", self.value, rhs.value), self.unit.sub(rhs.unit))

    def __mul__(self, other: object) -> Quantity:
        rhs = self._other(other)
        return Quantity(_operate("mul", self.value, rhs.value), self.unit.mul(rhs.unit))

    def __truediv__(self, other: object) -> Quantity:
        rhs = self._other(other)
        return Quantity(_operate("div", self.value, rhs.value), self.unit.div(rhs.unit))

    def to_ratio(self) -> Quantity:
        if self.unit == RATIO:
            return self
        if self.unit.kind is not UnitKind.PERCENT:
            raise UnitError(f"only percent normalizes to ratio, got {self.unit.key()}")
        unit = Unit(kind=UnitKind.RATIO, per_period=self.unit.per_period)
        return Quantity(_operate("div", self.value, _HUNDRED), unit)

    def to_percent(self) -> Quantity:
        if self.unit.kind is UnitKind.PERCENT:
            return self
        if self.unit.kind is not UnitKind.RATIO:
            raise UnitError(f"only ratio converts to percent, got {self.unit.key()}")
        unit = Unit(kind=UnitKind.PERCENT, per_period=self.unit.per_period)
        return Quantity(_operate("mul", self.value, _HUNDRED), unit)

    def quantize(self, quantum: Decimal) -> Quantity:
        require_decimal(quantum, "quantum")
        try:
            value = self.value.quantize(quantum, rounding=ROUND_HALF_EVEN, context=CALC_CONTEXT)
        except InvalidOperation as exc:
            raise FormulaError(f"cannot quantize {self.value} to {quantum}") from exc
        return Quantity(value, self.unit)


__all__ = [
    "CALC_CONTEXT",
    "PERCENT",
    "SAFE_ID",
    "Lineage",
    "Provenance",
    "Quantity",
    "canonical_decimal",
    "require_decimal",
    "require_safe_id",
]
