"""Dependency edges, structural validation, and fail-closed cycle detection (T0402, FR-MOD-001)."""

from __future__ import annotations

import sys

import pytest
from _fixtures import Q1, Q2, USD, assumption, driver, formula, output, rollup, source

from fel_calculation_engine.errors import (
    CycleError,
    GraphError,
    MissingInputError,
    PeriodError,
    ScenarioError,
    UnitError,
)
from fel_calculation_engine.graph import Edge, ModelGraph
from fel_calculation_engine.nodes import Operator
from fel_calculation_engine.periods import FiscalQuarter, FiscalYear
from fel_calculation_engine.units import COUNT, RATIO, currency


def test_edges_are_derived_from_node_inputs_with_roles() -> None:
    graph = ModelGraph.build(
        [source("a", "1"), source("b", "2"), formula("c", Operator.SUB, ("a", "b"))]
    )
    assert graph.edges == (
        Edge(source="a", target="c", role="operand[0]"),
        Edge(source="b", target="c", role="operand[1]"),
    )
    assert graph.dependents("a") == ("c",)
    assert graph.dependencies("c") == ("a", "b")
    assert graph.node("c").node_id == "c"


def test_topological_order_is_deterministic_and_respects_edges() -> None:
    nodes = [
        formula("z", Operator.ADD, ("y", "x")),
        source("y", "1"),
        formula("x", Operator.MUL, ("w", "r"), unit=USD),
        source("w", "2"),
        assumption("r", "0.5"),
    ]
    graph = ModelGraph.build(nodes)
    order = graph.order
    assert set(order) == {"z", "y", "x", "w", "r"}
    assert order.index("w") < order.index("x") < order.index("z")
    assert order.index("r") < order.index("x")
    assert order.index("y") < order.index("z")
    assert ModelGraph.build(list(reversed(nodes))).order == order


def test_missing_input_fails_closed() -> None:
    with pytest.raises(MissingInputError) as excinfo:
        ModelGraph.build([source("a", "1"), formula("c", Operator.ADD, ("a", "ghost"))])
    assert excinfo.value.details["missing"] == "ghost"
    assert excinfo.value.details["node_id"] == "c"


def test_duplicate_node_ids_are_rejected() -> None:
    with pytest.raises(GraphError):
        ModelGraph.build([source("a", "1"), source("a", "2")])


def test_direct_and_indirect_cycles_are_rejected_with_the_offending_path() -> None:
    with pytest.raises(CycleError) as excinfo:
        ModelGraph.build(
            [
                source("s", "1"),
                formula("a", Operator.ADD, ("s", "c")),
                formula("b", Operator.ADD, ("s", "a")),
                formula("c", Operator.ADD, ("s", "b")),
            ]
        )
    cycle = excinfo.value.cycle
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}
    assert excinfo.value.code == "CYCLE_DETECTED"


def test_two_node_cycle_is_rejected() -> None:
    with pytest.raises(CycleError):
        ModelGraph.build(
            [
                source("s", "1"),
                formula("a", Operator.ADD, ("s", "b")),
                formula("b", Operator.ADD, ("s", "a")),
            ]
        )


def test_a_cycle_longer_than_the_recursion_limit_still_raises_CycleError() -> None:
    """A big cyclic model must fail as a modelling error, not an interpreter one.

    The cycle *reporter* used to recurse once per node on the path, so a cycle
    longer than ``sys.getrecursionlimit()`` raised a bare ``RecursionError``.
    That is not a ``CalculationEngineError``, so it escaped every ``except``
    clause and every ``code``-based classification in this package — in a
    package whose stated target is 5,000-node graphs. Detection was always
    correct; only the reporter was recursive.
    """
    size = sys.getrecursionlimit() + 500
    nodes = [source("s", "1")]
    nodes += [formula(f"n{i}", Operator.ADD, ("s", f"n{(i + 1) % size}")) for i in range(size)]

    with pytest.raises(CycleError) as excinfo:
        ModelGraph.build(nodes)

    cycle = excinfo.value.cycle
    assert cycle[0] == cycle[-1], "the reported path is not closed"
    assert len(cycle) == size + 1
    assert excinfo.value.code == "CYCLE_DETECTED"


def test_formula_units_are_type_checked_at_build_time() -> None:
    with pytest.raises(UnitError):
        ModelGraph.build(
            [
                source("p", "1", unit=USD),
                source("q", "2", unit=COUNT),
                formula("r", Operator.ADD, ("p", "q")),
            ]
        )
    with pytest.raises(UnitError):  # USD * USD has no unit
        ModelGraph.build(
            [
                source("p", "1", unit=USD),
                source("q", "2", unit=USD),
                formula("r", Operator.MUL, ("p", "q")),
            ]
        )
    with pytest.raises(UnitError):  # declared RATIO but computes USD
        ModelGraph.build(
            [source("p", "1"), source("q", "2"), formula("r", Operator.ADD, ("p", "q"), unit=RATIO)]
        )


def test_formula_operands_must_share_the_output_period_kind() -> None:
    fy = source("y", "1", period=FiscalQuarter(2024, 4))
    with pytest.raises(PeriodError):
        ModelGraph.build(
            [
                fy,
                rollup("fy", ("y", "y2", "y3", "y4")),
                source("y2", "1", period=FiscalQuarter(2024, 1)),
                source("y3", "1", period=FiscalQuarter(2024, 2)),
                source("y4", "1", period=FiscalQuarter(2024, 3)),
                formula("mixed", Operator.ADD, ("y", "fy")),
            ]
        )


def test_rollup_year_requires_exactly_the_four_quarters_of_its_year() -> None:
    quarters = [source(f"q{i}", "1", period=FiscalQuarter(2024, i)) for i in (1, 2, 3, 4)]
    graph = ModelGraph.build([*quarters, rollup("fy", ("q1", "q2", "q3", "q4"))])
    assert graph.node("fy").period == FiscalYear(2024)
    with pytest.raises(PeriodError):
        ModelGraph.build(
            [
                *quarters[:3],
                source("q5", "1", period=FiscalQuarter(2025, 1)),
                rollup("fy", ("q1", "q2", "q3", "q5")),
            ]
        )
    with pytest.raises(PeriodError):
        ModelGraph.build(
            [*quarters[:3], source("q4", "1", period=Q1), rollup("fy", ("q1", "q2", "q3", "q4"))]
        )


def test_driver_and_output_must_match_their_source_unit_and_period() -> None:
    with pytest.raises(UnitError):
        ModelGraph.build([source("f", "1", unit=COUNT), driver("d", "f", unit=USD)])
    with pytest.raises(PeriodError):
        ModelGraph.build([source("f", "1", unit=COUNT), driver("d", "f", period=Q2)])
    with pytest.raises(UnitError):
        ModelGraph.build([source("f", "1"), output("o", "f", unit=currency("EUR"))])


def test_scenario_override_may_only_target_assumptions_and_drivers() -> None:
    from decimal import Decimal

    from _fixtures import AS_OF

    from fel_calculation_engine.nodes import ScenarioOverrideNode

    def override(target: str, unit=RATIO, period=Q1) -> ScenarioOverrideNode:  # type: ignore[no-untyped-def]
        return ScenarioOverrideNode(
            node_id=f"{target}-bull",
            label="bull",
            unit=unit,
            period=period,
            target=target,
            value=Decimal("0.2"),
            as_of=AS_OF,
            scenario_id="bull",
            assumption_id=f"asm-{target}-bull",
        )

    ModelGraph.build([assumption("g", "0.1"), override("g")])
    ModelGraph.build([source("f", "1", unit=COUNT), driver("d", "f"), override("d", unit=COUNT)])
    with pytest.raises(ScenarioError):
        ModelGraph.build([source("f", "1", unit=RATIO), override("f")])
    with pytest.raises(UnitError):
        ModelGraph.build([assumption("g", "0.1"), override("g", unit=COUNT)])
    with pytest.raises(PeriodError):
        ModelGraph.build([assumption("g", "0.1"), override("g", period=Q2)])
