"""The nine model-graph node kinds and their fail-closed invariants (T0401, spec §8.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fel_calculation_engine.errors import NodeValidationError, ValueTypeError
from fel_calculation_engine.nodes import (
    AggregationNode,
    AggregationOp,
    AnalystAssumptionNode,
    CheckOp,
    ForecastModelOutputNode,
    FormulaNode,
    Node,
    NodeKind,
    OperationalDriverNode,
    Operator,
    ReportedFinancialOutputNode,
    ScenarioOverrideNode,
    SourceFactNode,
    ValidationCheckNode,
)
from fel_calculation_engine.periods import FiscalQuarter, FiscalYear
from fel_calculation_engine.units import COUNT, RATIO, currency
from fel_calculation_engine.values import Provenance

USD = currency("USD")
Q1 = FiscalQuarter(2024, 1)
AS_OF = datetime(2024, 5, 1, tzinfo=UTC)


def _source(node_id: str = "rev-q1") -> SourceFactNode:
    return SourceFactNode(
        node_id=node_id,
        label="Revenue Q1",
        unit=USD,
        period=Q1,
        value=Decimal("1000.00"),
        as_of=AS_OF,
        source_span_id="span-1",
    )


def test_all_nine_node_kinds_exist_with_spec_names() -> None:
    assert {k.value for k in NodeKind} == {
        "source_fact",
        "analyst_assumption",
        "operational_driver",
        "formula",
        "aggregation",
        "scenario_override",
        "forecast_model_output",
        "validation_check",
        "reported_financial_output",
    }


def test_every_kind_is_constructible_and_reports_its_kind_and_provenance() -> None:
    nodes: list[Node] = [
        _source(),
        AnalystAssumptionNode(
            node_id="growth",
            label="Growth",
            unit=RATIO,
            period=Q1,
            value=Decimal("0.10"),
            as_of=AS_OF,
            assumption_id="asm-growth",
        ),
        OperationalDriverNode(node_id="units", label="Units", unit=COUNT, period=Q1, seed="rev-q1"),
        FormulaNode(
            node_id="rev-next",
            label="Next",
            unit=USD,
            period=Q1.next(),
            operator=Operator.MUL,
            operands=("rev-q1", "growth"),
            formula_version="growth-v1",
        ),
        AggregationNode(
            node_id="fy",
            label="FY",
            unit=USD,
            period=FiscalYear(2024),
            operator=AggregationOp.ROLLUP_YEAR,
            operands=("q1", "q2", "q3", "q4"),
        ),
        ScenarioOverrideNode(
            node_id="growth-bull",
            label="Bull growth",
            unit=RATIO,
            period=Q1,
            target="growth",
            value=Decimal("0.20"),
            as_of=AS_OF,
            scenario_id="bull",
            assumption_id="asm-growth-bull",
        ),
        ForecastModelOutputNode(
            node_id="fc",
            label="Forecast",
            unit=USD,
            period=Q1.next(),
            value=Decimal("1100"),
            as_of=AS_OF,
            forecast_run_id="run-1",
            dataset_cutoff=AS_OF,
            dataset_version="ds-v1",
        ),
        ValidationCheckNode(
            node_id="chk",
            label="Check",
            unit=USD,
            period=Q1,
            check=CheckOp.EQUALS,
            operands=("rev-q1", "rev-next"),
            tolerance=Decimal("0.01"),
        ),
        ReportedFinancialOutputNode(
            node_id="out",
            label="Reported revenue",
            unit=USD,
            period=Q1,
            source="rev-q1",
            metric_id="revenue",
        ),
    ]
    assert [n.kind for n in nodes] == list(NodeKind)
    expected = {
        NodeKind.SOURCE_FACT: Provenance.REPORTED,
        NodeKind.ANALYST_ASSUMPTION: Provenance.ASSUMPTION,
        NodeKind.SCENARIO_OVERRIDE: Provenance.ASSUMPTION,
        NodeKind.FORECAST_MODEL_OUTPUT: Provenance.FORECAST,
    }
    for node in nodes:
        assert node.provenance is expected.get(node.kind, Provenance.DERIVED)


def test_inputs_are_role_tagged_edges_in_declaration_order() -> None:
    assert _source().inputs() == ()
    driver = OperationalDriverNode(node_id="d", label="d", unit=USD, period=Q1, seed="rev-q1")
    assert driver.inputs() == (("seed", "rev-q1"),)
    formula = FormulaNode(
        node_id="f",
        label="f",
        unit=USD,
        period=Q1,
        operator=Operator.SUB,
        operands=("a", "b"),
        formula_version="v1",
    )
    assert formula.inputs() == (("operand[0]", "a"), ("operand[1]", "b"))
    override = ScenarioOverrideNode(
        node_id="o",
        label="o",
        unit=USD,
        period=Q1,
        target="a",
        value=Decimal(1),
        as_of=AS_OF,
        scenario_id="bull",
        assumption_id="asm-o",
    )
    assert override.inputs() == (("overrides", "a"),)
    out = ReportedFinancialOutputNode(
        node_id="r", label="r", unit=USD, period=Q1, source="a", metric_id="revenue"
    )
    assert out.inputs() == (("source", "a"),)


def test_nodes_are_frozen() -> None:
    node = _source()
    with pytest.raises(AttributeError):
        node.value = Decimal("2")  # type: ignore[misc]


@pytest.mark.parametrize("bad", [1000.0, 1000, "1000", Decimal("NaN"), Decimal("Infinity"), None])
def test_leaf_values_must_be_finite_decimals(bad: object) -> None:
    with pytest.raises(ValueTypeError):
        SourceFactNode(
            node_id="s",
            label="s",
            unit=USD,
            period=Q1,
            value=bad,  # type: ignore[arg-type]
            as_of=AS_OF,
            source_span_id="span-1",
        )
    with pytest.raises(ValueTypeError):
        AnalystAssumptionNode(
            node_id="a",
            label="a",
            unit=USD,
            period=Q1,
            value=bad,  # type: ignore[arg-type]
            as_of=AS_OF,
            assumption_id="asm",
        )


def test_assumptions_are_explicit_only_no_implicit_defaults() -> None:
    with pytest.raises(TypeError):
        AnalystAssumptionNode(  # type: ignore[call-arg]
            node_id="a", label="a", unit=USD, period=Q1, as_of=AS_OF, assumption_id="asm"
        )
    with pytest.raises(TypeError):
        AnalystAssumptionNode(  # type: ignore[call-arg]
            node_id="a", label="a", unit=USD, period=Q1, value=Decimal(1), as_of=AS_OF
        )
    with pytest.raises(TypeError):
        FormulaNode(  # type: ignore[call-arg]
            node_id="f", label="f", unit=USD, period=Q1, operator=Operator.ADD, operands=("a", "b")
        )


def test_lineage_ids_and_node_ids_are_validated_slugs() -> None:
    for bad_id in ("", "has space", "a|b", "x" * 129, "-leading"):
        with pytest.raises(NodeValidationError):
            _source(bad_id)
    with pytest.raises(NodeValidationError):
        SourceFactNode(
            node_id="s",
            label="s",
            unit=USD,
            period=Q1,
            value=Decimal(1),
            as_of=AS_OF,
            source_span_id="span 1",
        )
    with pytest.raises(NodeValidationError):
        AnalystAssumptionNode(
            node_id="a",
            label="a",
            unit=USD,
            period=Q1,
            value=Decimal(1),
            as_of=AS_OF,
            assumption_id="",
        )


def test_as_of_must_be_timezone_aware() -> None:
    with pytest.raises(NodeValidationError):
        SourceFactNode(
            node_id="s",
            label="s",
            unit=USD,
            period=Q1,
            value=Decimal(1),
            as_of=datetime(2024, 5, 1),
            source_span_id="span-1",
        )


def test_operator_arity_is_enforced() -> None:
    kwargs = dict(node_id="f", label="f", unit=USD, period=Q1, formula_version="v1")
    for op in (Operator.SUB, Operator.DIV):
        with pytest.raises(NodeValidationError):
            FormulaNode(operator=op, operands=("a",), **kwargs)  # type: ignore[arg-type]
        with pytest.raises(NodeValidationError):
            FormulaNode(operator=op, operands=("a", "b", "c"), **kwargs)  # type: ignore[arg-type]
    for op in (Operator.ADD, Operator.MUL):
        with pytest.raises(NodeValidationError):
            FormulaNode(operator=op, operands=("a",), **kwargs)  # type: ignore[arg-type]
    with pytest.raises(NodeValidationError):
        FormulaNode(operator=Operator.ADD, operands=("a", "a"), **kwargs)  # type: ignore[arg-type]
    with pytest.raises(NodeValidationError):
        FormulaNode(operator=Operator.ADD, operands=("a", "f"), **kwargs)  # type: ignore[arg-type]
    with pytest.raises(NodeValidationError):
        AggregationNode(
            node_id="g",
            label="g",
            unit=USD,
            period=FiscalYear(2024),
            operator=AggregationOp.ROLLUP_YEAR,
            operands=("a", "b", "c"),
        )
    with pytest.raises(NodeValidationError):
        AggregationNode(
            node_id="g",
            label="g",
            unit=USD,
            period=Q1,
            operator=AggregationOp.ROLLUP_YEAR,
            operands=("a", "b", "c", "d"),
        )
    with pytest.raises(NodeValidationError):
        ValidationCheckNode(
            node_id="c",
            label="c",
            unit=USD,
            period=Q1,
            check=CheckOp.NON_NEGATIVE,
            operands=("a", "b"),
        )
    with pytest.raises(ValueTypeError):
        ValidationCheckNode(
            node_id="c",
            label="c",
            unit=USD,
            period=Q1,
            check=CheckOp.EQUALS,
            operands=("a", "b"),
            tolerance=0.01,  # type: ignore[arg-type]
        )


def test_reported_output_quantum_must_be_explicit_for_non_currency_units() -> None:
    ReportedFinancialOutputNode(
        node_id="r", label="r", unit=USD, period=Q1, source="a", metric_id="revenue"
    )
    with pytest.raises(NodeValidationError):
        ReportedFinancialOutputNode(
            node_id="r", label="r", unit=RATIO, period=Q1, source="a", metric_id="gross_margin"
        )
    node = ReportedFinancialOutputNode(
        node_id="r",
        label="r",
        unit=RATIO,
        period=Q1,
        source="a",
        metric_id="gross_margin",
        quantum=Decimal("0.0001"),
    )
    assert node.quantum == Decimal("0.0001")
    with pytest.raises(NodeValidationError):
        ReportedFinancialOutputNode(
            node_id="r",
            label="r",
            unit=USD,
            period=Q1,
            source="a",
            metric_id="revenue",
            quantum=Decimal("0"),
        )
