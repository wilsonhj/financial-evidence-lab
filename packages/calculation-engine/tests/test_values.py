"""Decimal-only quantities and exactly-one-lineage provenance (T0401 / T0403, Constitution II)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_calculation_engine.errors import LineageError, UnitError, ValueTypeError
from fel_calculation_engine.units import COUNT, PERCENT, RATIO, currency
from fel_calculation_engine.values import (
    Lineage,
    Provenance,
    Quantity,
    canonical_decimal,
    require_decimal,
)

USD = currency("USD")


@pytest.mark.parametrize(
    "bad",
    [
        1.5,
        1,
        "1.5",
        True,
        None,
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_only_finite_decimals_are_values(bad: object) -> None:
    with pytest.raises(ValueTypeError):
        require_decimal(bad, "value")
    with pytest.raises(ValueTypeError):
        Quantity(bad, USD)  # type: ignore[arg-type]


def test_quantity_arithmetic_is_exact_decimal_with_unit_algebra() -> None:
    price = Quantity(Decimal("19.99"), USD)
    volume = Quantity(Decimal("3"), COUNT)
    revenue = price * volume
    assert revenue == Quantity(Decimal("59.97"), USD)
    assert revenue.value == Decimal("59.97")
    assert (revenue / volume) == Quantity(Decimal("19.99"), USD)
    assert (revenue + revenue).value == Decimal("119.94")
    assert (revenue - revenue).unit == USD
    with pytest.raises(UnitError):
        _ = price + volume
    with pytest.raises(UnitError):
        _ = price * price


def test_quantity_division_by_zero_fails_closed() -> None:
    from fel_calculation_engine.errors import FormulaError

    with pytest.raises(FormulaError):
        _ = Quantity(Decimal("1"), USD) / Quantity(Decimal("0"), COUNT)


def test_quantity_rejects_float_operands() -> None:
    with pytest.raises(ValueTypeError):
        _ = Quantity(Decimal("1"), USD) * 1.5  # type: ignore[operator]


def test_percent_normalization_is_exact_and_symmetric() -> None:
    margin = Quantity(Decimal("62.5"), PERCENT)
    ratio = margin.to_ratio()
    assert ratio == Quantity(Decimal("0.625"), RATIO)
    assert ratio.to_percent() == margin
    assert Quantity(Decimal("0.1"), RATIO).to_ratio().unit == RATIO
    with pytest.raises(UnitError):
        Quantity(Decimal("1"), USD).to_ratio()
    with pytest.raises(UnitError):
        _ = margin * Quantity(Decimal("100"), USD)
    assert (ratio * Quantity(Decimal("100"), USD)).value == Decimal("62.500")


def test_canonical_decimal_collapses_representation_but_not_value() -> None:
    assert canonical_decimal(Decimal("1.50")) == canonical_decimal(Decimal("1.5"))
    assert canonical_decimal(Decimal("1E+2")) == "100"
    assert canonical_decimal(Decimal("-0.00")) == "0"
    assert canonical_decimal(Decimal("0.000001")) == "0.000001"
    assert canonical_decimal(Decimal("1.5")) != canonical_decimal(Decimal("1.51"))


def test_lineage_carries_exactly_one_field_matched_to_its_kind() -> None:
    reported = Lineage(Provenance.REPORTED, source_span_id="span-1")
    assert reported.identity() == ("reported", "span-1")
    assumption = Lineage(Provenance.ASSUMPTION, assumption_id="asm-1")
    assert assumption.identity() == ("assumption", "asm-1")
    forecast = Lineage(Provenance.FORECAST, forecast_run_id="run-1")
    assert forecast.identity() == ("forecast", "run-1")
    derived = Lineage(Provenance.DERIVED, derived_from=("r-b", "r-a"))
    assert derived.identity() == ("derived", "r-a", "r-b")


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(provenance=Provenance.REPORTED),
        dict(provenance=Provenance.REPORTED, source_span_id="s", assumption_id="a"),
        dict(provenance=Provenance.REPORTED, assumption_id="a"),
        dict(provenance=Provenance.ASSUMPTION, source_span_id="s"),
        dict(provenance=Provenance.ASSUMPTION, assumption_id="a", derived_from=("r",)),
        dict(provenance=Provenance.DERIVED),
        dict(provenance=Provenance.DERIVED, derived_from=("r",), forecast_run_id="f"),
        dict(provenance=Provenance.FORECAST, source_span_id="s", forecast_run_id="f"),
        dict(provenance=Provenance.FORECAST),
        dict(provenance=Provenance.REPORTED, source_span_id=""),
        dict(provenance=Provenance.REPORTED, source_span_id="has space"),
        dict(provenance=Provenance.DERIVED, derived_from=("r", "r")),
    ],
)
def test_lineage_rejects_missing_extra_or_malformed_fields(kwargs: dict[str, object]) -> None:
    with pytest.raises(LineageError):
        Lineage(**kwargs)  # type: ignore[arg-type]


def test_provenance_is_the_constitution_four_way_split() -> None:
    assert {p.value for p in Provenance} == {"reported", "assumption", "derived", "forecast"}
