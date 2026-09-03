"""Server-side Decimal calculation engine with typed units (T0403, FR-MOD-002)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from _fixtures import (
    AS_OF,
    CUTOFF,
    Q1,
    Q2,
    USD,
    assumption,
    formula,
    output,
    revenue_model,
    rollup,
    source,
)

from fel_calculation_engine.engine import CalcResult, EvaluationResult, evaluate
from fel_calculation_engine.errors import CutoffViolationError, FormulaError, ValueTypeError
from fel_calculation_engine.nodes import (
    CheckOp,
    ForecastModelOutputNode,
    FormulaNode,
    NodeKind,
    Operator,
    ReportedFinancialOutputNode,
    ValidationCheckNode,
)
from fel_calculation_engine.periods import FiscalQuarter, FiscalYear
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.units import COUNT, RATIO, Unit, currency
from fel_calculation_engine.values import CALC_CONTEXT, Lineage, Provenance, Quantity


def test_revenue_model_evaluates_exactly_with_full_provenance() -> None:
    snapshot = GraphSnapshot.build("m", revenue_model())
    run = evaluate(snapshot, cutoff=CUTOFF)
    assert isinstance(run, EvaluationResult)
    assert run.snapshot_id == snapshot.snapshot_id
    assert run.quantity("revenue") == Quantity(Decimal("19990.00"), USD)
    assert run.quantity("growth-factor") == Quantity(Decimal("1.10"), RATIO)
    assert run.quantity("revenue-next") == Quantity(Decimal("21989.0000"), USD)
    assert run.quantity("reported-revenue") == Quantity(Decimal("19990.00"), USD)
    revenue = run.result("revenue")
    assert revenue.kind is NodeKind.FORMULA
    assert revenue.provenance is Provenance.DERIVED
    assert revenue.lineage == Lineage(
        Provenance.DERIVED,
        derived_from=(run.result("price").result_id, run.result("units").result_id),
    )
    assert revenue.input_result_ids == (
        run.result("price").result_id,
        run.result("units").result_id,
    )
    assert revenue.formula_version == "v1"
    assert run.result("price").lineage == Lineage(Provenance.REPORTED, source_span_id="span-price")
    assert run.result("growth").lineage == Lineage(
        Provenance.ASSUMPTION, assumption_id="asm-growth"
    )
    assert run.result("units").lineage.derived_from == (run.result("units-fact").result_id,)
    assert run.order == snapshot.graph.order
    assert run.result("revenue-next").period == Q2


def test_results_are_immutable_and_deterministic() -> None:
    snapshot = GraphSnapshot.build("m", revenue_model())
    run_a = evaluate(snapshot, cutoff=CUTOFF)
    run_b = evaluate(snapshot, cutoff=CUTOFF)
    assert run_a == run_b
    assert run_a.evaluation_id == run_b.evaluation_id
    assert {k: r.result_id for k, r in run_a.results.items()} == {
        k: r.result_id for k, r in run_b.results.items()
    }
    with pytest.raises(TypeError):
        run_a.results["revenue"] = run_a.results["price"]  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        run_a.results["revenue"].value = Decimal(0)  # type: ignore[misc]


def test_available_at_is_derived_from_parents_never_from_the_caller() -> None:
    early = datetime(2024, 4, 1, tzinfo=UTC)
    late = datetime(2024, 5, 15, tzinfo=UTC)
    nodes = [
        source("a", "1", as_of=early),
        source("b", "2", as_of=late),
        formula("c", Operator.ADD, ("a", "b")),
        assumption("k", "3", unit=USD, as_of=early),
        formula("d", Operator.ADD, ("c", "k")),
    ]
    run = evaluate(GraphSnapshot.build("m", nodes), cutoff=CUTOFF)
    assert run.result("a").available_at == early
    assert run.result("c").available_at == late
    assert run.result("d").available_at == late
    with pytest.raises(TypeError):
        FormulaNode(  # type: ignore[call-arg]
            node_id="x",
            label="x",
            unit=USD,
            period=Q1,
            operator=Operator.ADD,
            operands=("a", "b"),
            formula_version="v1",
            as_of=early,
        )


def test_cutoff_is_enforced_fail_closed_on_every_leaf() -> None:
    snapshot = GraphSnapshot.build("m", revenue_model())
    with pytest.raises(CutoffViolationError) as excinfo:
        evaluate(snapshot, cutoff=AS_OF - timedelta(seconds=1))
    assert excinfo.value.code == "TEMPORAL_SCOPE_VIOLATION"
    assert excinfo.value.details["node_id"] in {n.node_id for n in revenue_model()}
    assert evaluate(snapshot, cutoff=AS_OF).result("revenue").available_at == AS_OF
    with pytest.raises(CutoffViolationError):
        evaluate(snapshot, cutoff=datetime(2024, 6, 30))  # naive cutoff is a violation


def test_forecast_outputs_pin_dataset_cutoff_and_must_not_look_ahead() -> None:
    forecast = ForecastModelOutputNode(
        node_id="fc",
        label="fc",
        unit=USD,
        period=Q2,
        value=Decimal("5"),
        as_of=AS_OF,
        forecast_run_id="run-1",
        dataset_cutoff=AS_OF + timedelta(days=30),
        dataset_version="ds-1",
    )
    snapshot = GraphSnapshot.build("m", [forecast])
    with pytest.raises(CutoffViolationError):
        evaluate(snapshot, cutoff=AS_OF)
    run = evaluate(snapshot, cutoff=AS_OF + timedelta(days=30))
    assert run.result("fc").provenance is Provenance.FORECAST
    assert run.result("fc").lineage == Lineage(Provenance.FORECAST, forecast_run_id="run-1")


def test_division_by_zero_fails_closed_at_evaluation() -> None:
    nodes = [source("n", "1"), source("d", "0"), formula("q", Operator.DIV, ("n", "d"), unit=RATIO)]
    with pytest.raises(FormulaError) as excinfo:
        evaluate(GraphSnapshot.build("m", nodes), cutoff=CUTOFF)
    assert excinfo.value.details["node_id"] == "q"


def test_terminal_value_style_guard_wacc_must_exceed_growth() -> None:
    """A Gordon-growth denominator (wacc - g) must be positive: the check flags it and
    the division itself fails closed when they are equal, across every sensitivity band."""
    for wacc, growth in (("0.08", "0.08"), ("0.07", "0.08"), ("0.09", "0.08")):
        nodes = [
            assumption("wacc", wacc),
            assumption("g", growth),
            formula("spread", Operator.SUB, ("wacc", "g"), unit=RATIO),
            ValidationCheckNode(
                node_id="wacc-gt-g",
                label="wacc > g",
                unit=RATIO,
                period=Q1,
                check=CheckOp.GREATER_OR_EQUAL,
                operands=("wacc", "g"),
                tolerance=None,
            ),
            source("fcf", "100"),
            formula("tv", Operator.DIV, ("fcf", "spread")),
        ]
        snapshot = GraphSnapshot.build("m", nodes)
        if wacc == growth:
            with pytest.raises(FormulaError):
                evaluate(snapshot, cutoff=CUTOFF)
        else:
            run = evaluate(snapshot, cutoff=CUTOFF)
            assert run.result("wacc-gt-g").passed is (Decimal(wacc) >= Decimal(growth))
            assert ("wacc-gt-g" in run.failed_checks) is (Decimal(wacc) < Decimal(growth))


def test_validation_checks_report_pass_fail_and_residual() -> None:
    nodes = [
        source("a", "100.00"),
        source("b", "100.004"),
        ValidationCheckNode(
            node_id="eq",
            label="eq",
            unit=USD,
            period=Q1,
            check=CheckOp.EQUALS,
            operands=("a", "b"),
            tolerance=Decimal("0.01"),
        ),
        ValidationCheckNode(
            node_id="eq-strict",
            label="eq",
            unit=USD,
            period=Q1,
            check=CheckOp.EQUALS,
            operands=("a", "b"),
            tolerance=None,
        ),
        source("neg", "-1"),
        ValidationCheckNode(
            node_id="nonneg",
            label="nn",
            unit=USD,
            period=Q1,
            check=CheckOp.NON_NEGATIVE,
            operands=("neg",),
        ),
        ValidationCheckNode(
            node_id="le",
            label="le",
            unit=USD,
            period=Q1,
            check=CheckOp.LESS_OR_EQUAL,
            operands=("a", "b"),
        ),
    ]
    run = evaluate(GraphSnapshot.build("m", nodes), cutoff=CUTOFF)
    assert run.result("eq").passed is True
    assert run.result("eq").value == Decimal("-0.004")
    assert run.result("eq-strict").passed is False
    assert run.result("nonneg").passed is False
    assert run.result("le").passed is True
    assert run.failed_checks == ("eq-strict", "nonneg")
    assert run.result("price" if False else "eq").kind is NodeKind.VALIDATION_CHECK


def test_rollup_year_sums_the_four_quarters() -> None:
    quarters = [source(f"q{i}", f"{i}.5", period=FiscalQuarter(2024, i)) for i in (1, 2, 3, 4)]
    run = evaluate(
        GraphSnapshot.build("m", [*quarters, rollup("fy", ("q4", "q3", "q2", "q1"))]), cutoff=CUTOFF
    )
    assert run.quantity("fy") == Quantity(Decimal("12.0"), USD)
    assert run.result("fy").period == FiscalYear(2024)


def test_rounding_happens_once_at_the_reported_edge_and_never_compounds() -> None:
    # Ten chained multiplications by 1.005 on 100.005 USD; quantizing every step would drift.
    nodes = [source("x0", "100.005"), assumption("f", "1.005")]
    for i in range(10):
        nodes.append(formula(f"x{i + 1}", Operator.MUL, (f"x{i}", "f")))
    nodes.append(output("out", "x10"))
    run = evaluate(GraphSnapshot.build("m", nodes), cutoff=CUTOFF)
    with localcontext(CALC_CONTEXT):
        exact = Decimal("100.005") * Decimal("1.005") ** 10
    assert run.quantity("x10").value == exact
    assert run.quantity("out").value == exact.quantize(Decimal("0.01"))
    stepwise = Decimal("100.005")
    for _ in range(10):
        stepwise = (stepwise * Decimal("1.005")).quantize(Decimal("0.01"))
    assert run.quantity("out").value != stepwise  # compounding would have drifted by cents
    assert run.result("out").lineage.derived_from == (run.result("x10").result_id,)


def test_reported_output_uses_iso_4217_minor_units_or_explicit_quantum() -> None:
    jpy = currency("JPY")
    kwd = currency("KWD")
    nodes = [
        source("y", "1234.56", unit=jpy),
        output("y-out", "y", unit=jpy),
        source("k", "1.23456", unit=kwd),
        output("k-out", "k", unit=kwd),
        source("r", "0.123456", unit=RATIO),
        ReportedFinancialOutputNode(
            node_id="r-out",
            label="r",
            unit=RATIO,
            period=Q1,
            source="r",
            metric_id="gm",
            quantum=Decimal("0.0001"),
        ),
        source("half", "2.5", unit=jpy),
        output("half-out", "half", unit=jpy),
    ]
    run = evaluate(GraphSnapshot.build("m", nodes), cutoff=CUTOFF)
    assert run.quantity("y-out").value == Decimal("1235")
    assert run.quantity("k-out").value == Decimal("1.235")
    assert run.quantity("r-out").value == Decimal("0.1235")
    assert run.quantity("half-out").value == Decimal("2")  # banker's rounding, ties to even


def test_driver_seeded_from_an_approved_fact_recalculates_downstream(tmp_path: object) -> None:
    """Milestone 4 exit criterion: an approved extraction seeds a driver, downstream
    outputs recalculate, and provenance is complete."""
    base = GraphSnapshot.build("m", revenue_model())
    run_base = evaluate(base, cutoff=CUTOFF)
    reseeded = base.with_nodes([source("units-fact", "1200", unit=COUNT, span="span-approved-2")])
    run_new = evaluate(reseeded, cutoff=CUTOFF)
    assert run_new.quantity("revenue").value == Decimal("23988.00")
    assert (
        run_new.result("units").lineage.derived_from
        != run_base.result("units").lineage.derived_from
    )
    assert run_new.result("price").result_id == run_base.result("price").result_id
    assert run_new.result("units-fact").lineage == Lineage(
        Provenance.REPORTED, source_span_id="span-approved-2"
    )
    chain = run_new.trace("reported-revenue")
    assert [r.node_id for r in chain] == [
        "reported-revenue",
        "revenue",
        "price",
        "units",
        "units-fact",
    ]


def test_evaluate_rejects_non_snapshot_inputs() -> None:
    with pytest.raises(ValueTypeError):
        evaluate(revenue_model(), cutoff=CUTOFF)  # type: ignore[arg-type]


def test_calc_result_requires_finite_decimal_value() -> None:
    run = evaluate(GraphSnapshot.build("m", revenue_model()), cutoff=CUTOFF)
    good = run.result("price")
    with pytest.raises(ValueTypeError):
        dataclasses.replace(good, value=Decimal("NaN"))
    with pytest.raises(ValueTypeError):
        dataclasses.replace(good, value=1.0)  # type: ignore[arg-type]
    assert isinstance(good, CalcResult)
    assert isinstance(good.unit, Unit)
