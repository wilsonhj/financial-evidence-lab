"""Shared builders for calculation-engine tests (not collected by pytest)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fel_calculation_engine.nodes import (
    AggregationNode,
    AggregationOp,
    AnalystAssumptionNode,
    FormulaNode,
    Node,
    OperationalDriverNode,
    Operator,
    ReportedFinancialOutputNode,
    SourceFactNode,
)
from fel_calculation_engine.periods import FiscalQuarter, FiscalYear
from fel_calculation_engine.units import COUNT, RATIO, Unit, currency

USD = currency("USD")
Q1 = FiscalQuarter(2024, 1)
Q2 = FiscalQuarter(2024, 2)
AS_OF = datetime(2024, 5, 1, tzinfo=UTC)
CUTOFF = datetime(2024, 6, 30, tzinfo=UTC)


def source(
    node_id: str,
    value: str,
    *,
    unit: Unit = USD,
    period: FiscalQuarter = Q1,
    as_of: datetime = AS_OF,
    span: str | None = None,
) -> SourceFactNode:
    return SourceFactNode(
        node_id=node_id,
        label=node_id,
        unit=unit,
        period=period,
        value=Decimal(value),
        as_of=as_of,
        source_span_id=span or f"span-{node_id}",
    )


def assumption(
    node_id: str,
    value: str,
    *,
    unit: Unit = RATIO,
    period: FiscalQuarter = Q1,
    as_of: datetime = AS_OF,
) -> AnalystAssumptionNode:
    return AnalystAssumptionNode(
        node_id=node_id,
        label=node_id,
        unit=unit,
        period=period,
        value=Decimal(value),
        as_of=as_of,
        assumption_id=f"asm-{node_id}",
    )


def driver(node_id: str, seed: str, *, unit: Unit = COUNT, period: FiscalQuarter = Q1) -> Node:
    return OperationalDriverNode(
        node_id=node_id, label=node_id, unit=unit, period=period, seed=seed
    )


def formula(
    node_id: str,
    operator: Operator,
    operands: tuple[str, ...],
    *,
    unit: Unit = USD,
    period: FiscalQuarter = Q1,
    version: str = "v1",
) -> FormulaNode:
    return FormulaNode(
        node_id=node_id,
        label=node_id,
        unit=unit,
        period=period,
        operator=operator,
        operands=operands,
        formula_version=version,
    )


def rollup(node_id: str, operands: tuple[str, ...], *, unit: Unit = USD) -> AggregationNode:
    return AggregationNode(
        node_id=node_id,
        label=node_id,
        unit=unit,
        period=FiscalYear(2024),
        operator=AggregationOp.ROLLUP_YEAR,
        operands=operands,
    )


def output(node_id: str, src: str, *, unit: Unit = USD, period: FiscalQuarter = Q1) -> Node:
    return ReportedFinancialOutputNode(
        node_id=node_id, label=node_id, unit=unit, period=period, source=src, metric_id="revenue"
    )


def revenue_model() -> list[Node]:
    """price × units = revenue; revenue × (1 + growth) = next-quarter revenue; reported output."""
    return [
        source("price", "19.99", unit=USD),
        source("units-fact", "1000", unit=COUNT),
        driver("units", "units-fact"),
        formula("revenue", Operator.MUL, ("price", "units")),
        assumption("growth", "0.10"),
        assumption("one", "1"),
        formula("growth-factor", Operator.ADD, ("one", "growth"), unit=RATIO),
        formula("revenue-next", Operator.MUL, ("revenue", "growth-factor"), period=Q2),
        output("reported-revenue", "revenue"),
    ]
