"""Deterministic synthetic models for benchmarks and demos (T0410).

``build_synthetic_model(n, seed=...)`` returns exactly ``n`` valid nodes that
exercise all nine node kinds in the proportions of a real revenue/gross-profit
model: per segment a price fact, a units fact seeding a driver, a revenue
formula, a cost-ratio assumption, cost and gross-profit formulas, a validation
check, a reported output and a forecast leaf; every four quarterly segments roll
up into a fiscal-year aggregation and every eighth segment carries a scenario
override. The same ``(n, seed)`` always yields the same snapshot id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from random import Random

from fel_calculation_engine.nodes import (
    AggregationNode,
    AggregationOp,
    AnalystAssumptionNode,
    CheckOp,
    ForecastModelOutputNode,
    FormulaNode,
    Node,
    OperationalDriverNode,
    Operator,
    ReportedFinancialOutputNode,
    ScenarioOverrideNode,
    SourceFactNode,
    ValidationCheckNode,
)
from fel_calculation_engine.periods import FiscalQuarter, FiscalYear
from fel_calculation_engine.units import COUNT, RATIO, currency

SYNTHETIC_AS_OF = datetime(2024, 5, 1, tzinfo=UTC)
_SEGMENT_SIZE = 10


def _segment(i: int, rng: Random, *, override: bool) -> list[Node]:
    usd = currency("USD")
    period = FiscalQuarter(2024, (i % 4) + 1)
    price = Decimal(f"{rng.randint(100, 99_999)}.{rng.randint(0, 99):02d}")
    units = Decimal(rng.randint(1, 100_000))
    ratio = Decimal(f"0.{rng.randint(10, 90):02d}")
    cost_ratio_ref = f"v{i}" if override else f"m{i}"
    nodes: list[Node] = [
        SourceFactNode(
            node_id=f"p{i}",
            label=f"price {i}",
            unit=usd,
            period=period,
            value=price,
            as_of=SYNTHETIC_AS_OF,
            source_span_id=f"span-p{i}",
        ),
        SourceFactNode(
            node_id=f"u{i}",
            label=f"units {i}",
            unit=COUNT,
            period=period,
            value=units,
            as_of=SYNTHETIC_AS_OF,
            source_span_id=f"span-u{i}",
        ),
        OperationalDriverNode(
            node_id=f"d{i}", label=f"units driver {i}", unit=COUNT, period=period, seed=f"u{i}"
        ),
        FormulaNode(
            node_id=f"r{i}",
            label=f"revenue {i}",
            unit=usd,
            period=period,
            operator=Operator.MUL,
            operands=(f"p{i}", f"d{i}"),
            formula_version="revenue-v1",
        ),
        AnalystAssumptionNode(
            node_id=f"m{i}",
            label=f"cost ratio {i}",
            unit=RATIO,
            period=period,
            value=ratio,
            as_of=SYNTHETIC_AS_OF,
            assumption_id=f"asm-m{i}",
        ),
        FormulaNode(
            node_id=f"c{i}",
            label=f"cost {i}",
            unit=usd,
            period=period,
            operator=Operator.MUL,
            operands=(f"r{i}", cost_ratio_ref),
            formula_version="cost-v1",
        ),
        FormulaNode(
            node_id=f"g{i}",
            label=f"gross profit {i}",
            unit=usd,
            period=period,
            operator=Operator.SUB,
            operands=(f"r{i}", f"c{i}"),
            formula_version="gp-v1",
        ),
        ValidationCheckNode(
            node_id=f"k{i}",
            label=f"gp <= revenue {i}",
            unit=usd,
            period=period,
            check=CheckOp.LESS_OR_EQUAL,
            operands=(f"g{i}", f"r{i}"),
        ),
        ReportedFinancialOutputNode(
            node_id=f"o{i}",
            label=f"reported gp {i}",
            unit=usd,
            period=period,
            source=f"g{i}",
            metric_id="gross_profit",
        ),
        ForecastModelOutputNode(
            node_id=f"f{i}",
            label=f"forecast {i}",
            unit=usd,
            period=period.next(),
            value=price * units,
            as_of=SYNTHETIC_AS_OF,
            forecast_run_id=f"run-{i}",
            dataset_cutoff=SYNTHETIC_AS_OF,
            dataset_version="ds-synthetic",
        ),
    ]
    if override:
        nodes.append(
            ScenarioOverrideNode(
                node_id=f"v{i}",
                label=f"bull cost ratio {i}",
                unit=RATIO,
                period=period,
                value=ratio - Decimal("0.05"),
                as_of=SYNTHETIC_AS_OF,
                target=f"m{i}",
                scenario_id="bull",
                assumption_id=f"bull:m{i}",
            )
        )
    return nodes


def build_synthetic_model(node_count: int, *, seed: int = 63) -> list[Node]:
    if node_count < 1:
        raise ValueError("node_count must be positive")
    rng = Random(seed)  # noqa: S311 - deterministic fixture generation, not security
    nodes: list[Node] = []
    i = 0
    while True:
        override = i % 8 == 0
        rollup = i % 4 == 3
        needed = _SEGMENT_SIZE + int(override) + int(rollup)
        if len(nodes) + needed > node_count:
            break
        nodes.extend(_segment(i, rng, override=override))
        if rollup:
            nodes.append(
                AggregationNode(
                    node_id=f"y{i // 4}",
                    label=f"FY gross profit {i // 4}",
                    unit=currency("USD"),
                    period=FiscalYear(2024),
                    operator=AggregationOp.ROLLUP_YEAR,
                    operands=tuple(f"g{j}" for j in range(i - 3, i + 1)),
                )
            )
        i += 1
    pad = 0
    while len(nodes) < node_count:
        nodes.append(
            SourceFactNode(
                node_id=f"pad{pad}",
                label=f"pad {pad}",
                unit=currency("USD"),
                period=FiscalQuarter(2024, 1),
                value=Decimal(pad),
                as_of=SYNTHETIC_AS_OF,
                source_span_id=f"span-pad{pad}",
            )
        )
        pad += 1
    return nodes


__all__ = ["SYNTHETIC_AS_OF", "build_synthetic_model"]
