"""Server-side Decimal calculation engine (T0403, FR-MOD-002).

``evaluate`` walks a snapshot's topological order once under an evaluation
``cutoff`` and produces one immutable :class:`CalcResult` per node:

* values are finite Decimals computed under :data:`CALC_CONTEXT` with the
  typed-unit algebra — nothing is quantized until a reported-output node;
* ``available_at`` is the node's own availability bound for leaves (the maximum
  of ``as_of`` and ``dataset_cutoff`` for forecasts) and the maximum of its
  parents' ``available_at`` for derived nodes — a caller cannot supply it
  (derived nodes have no ``as_of`` field), and every leaf newer than the cutoff
  raises :class:`CutoffViolationError` (Constitution I, no look-ahead);
* ``result_id`` is a SHA-256 over typed canonical JSON of the node definition,
  the parents' result ids and the cutoff, so an unchanged sub-graph re-hashes
  to identical ids and any upstream change propagates downstream only;
* lineage follows the exactly-one-by-kind rule and is retained through every
  recalculation (``trace`` walks it back to the source spans and assumptions).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from time import perf_counter
from types import MappingProxyType

from fel_calculation_engine.canonical import content_hash, sha256_hex
from fel_calculation_engine.errors import (
    CalculationEngineError,
    CutoffViolationError,
    FormulaError,
    IterationConvergenceError,
    MissingInputError,
    UnitError,
    ValueTypeError,
)
from fel_calculation_engine.formulas import evaluate_formula
from fel_calculation_engine.iteration import ITERATION_ALGORITHM, IterationGroup, IterationRun
from fel_calculation_engine.nodes import (
    AggregationNode,
    AnalystAssumptionNode,
    CheckOp,
    ExpressionFormulaNode,
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
from fel_calculation_engine.periods import FiscalPeriod
from fel_calculation_engine.rounding import minor_unit_quantum
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.telemetry import TelemetrySink, emit
from fel_calculation_engine.units import Unit
from fel_calculation_engine.values import (
    CALC_CONTEXT,
    Lineage,
    Provenance,
    Quantity,
    require_decimal,
)

RESULT_SCHEMA = "fel-calc-result/v1"
EVALUATION_SCHEMA = "fel-calc-evaluation/v1"
_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class CalcResult:
    result_id: str
    node_id: str
    kind: NodeKind
    provenance: Provenance
    value: Decimal
    unit: Unit
    period: FiscalPeriod
    available_at: datetime
    lineage: Lineage
    input_result_ids: tuple[str, ...]
    formula_version: str | None = None
    passed: bool | None = None
    iteration_run_id: str | None = None

    def __post_init__(self) -> None:
        require_decimal(self.value, "CalcResult.value")
        if self.available_at.tzinfo is None:
            raise ValueTypeError("CalcResult.available_at must be timezone-aware")

    @property
    def quantity(self) -> Quantity:
        return Quantity(self.value, self.unit)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    evaluation_id: str
    snapshot_id: str
    cutoff: datetime
    order: tuple[str, ...]
    results: Mapping[str, CalcResult]
    failed_checks: tuple[str, ...]
    iteration_runs: Mapping[str, IterationRun] = field(default_factory=lambda: MappingProxyType({}))

    def result(self, node_id: str) -> CalcResult:
        try:
            return self.results[node_id]
        except KeyError as exc:
            raise MissingInputError(f"no result for node {node_id!r}", missing=node_id) from exc

    def quantity(self, node_id: str) -> Quantity:
        return self.result(node_id).quantity

    def trace(self, node_id: str) -> tuple[CalcResult, ...]:
        """Pre-order provenance walk from ``node_id`` back to its sources and assumptions."""
        by_result_id = {r.result_id: r for r in self.results.values()}
        seen: set[str] = set()
        chain: list[CalcResult] = []
        stack = [self.result(node_id)]
        while stack:
            current = stack.pop()
            if current.result_id in seen:
                continue
            seen.add(current.result_id)
            chain.append(current)
            stack.extend(by_result_id[rid] for rid in reversed(current.input_result_ids))
        return tuple(chain)


def _require_available(node: Node, stamp: datetime, cutoff: datetime, what: str) -> None:
    if stamp > cutoff:
        raise CutoffViolationError(
            f"{node.node_id}: {what} {stamp.isoformat()} is after cutoff {cutoff.isoformat()}",
            node_id=node.node_id,
            available_at=stamp.isoformat(),
            cutoff=cutoff.isoformat(),
        )


def _fold(node: FormulaNode, inputs: list[CalcResult]) -> Quantity:
    acc = inputs[0].quantity
    for parent in inputs[1:]:
        rhs = parent.quantity
        if node.operator is Operator.ADD:
            acc = acc + rhs
        elif node.operator is Operator.SUB:
            acc = acc - rhs
        elif node.operator is Operator.MUL:
            acc = acc * rhs
        else:
            acc = acc / rhs
    return acc


def _check(node: ValidationCheckNode, inputs: list[CalcResult]) -> tuple[Decimal, bool]:
    left = inputs[0].quantity
    if node.check is CheckOp.NON_NEGATIVE:
        return left.value, left.value >= _ZERO
    residual = left - inputs[1].quantity
    if node.check is CheckOp.EQUALS:
        tolerance = node.tolerance if node.tolerance is not None else _ZERO
        return residual.value, abs(residual.value) <= tolerance
    if node.check is CheckOp.LESS_OR_EQUAL:
        return residual.value, residual.value <= _ZERO
    return residual.value, residual.value >= _ZERO


def _compute(
    node: Node, inputs: list[CalcResult], cutoff: datetime
) -> tuple[Quantity, datetime, Lineage, str | None, bool | None]:
    if isinstance(node, SourceFactNode | AnalystAssumptionNode | ScenarioOverrideNode):
        _require_available(node, node.as_of, cutoff, "as_of")
        return node.lineage_quantity(), node.as_of, node.lineage(), None, None
    if isinstance(node, ForecastModelOutputNode):
        _require_available(node, node.as_of, cutoff, "as_of")
        _require_available(node, node.dataset_cutoff, cutoff, "dataset_cutoff")
        available_at = max(node.as_of, node.dataset_cutoff)
        return node.lineage_quantity(), available_at, node.lineage(), None, None

    available_at = max(parent.available_at for parent in inputs)
    lineage = Lineage(Provenance.DERIVED, derived_from=tuple(p.result_id for p in inputs))
    if isinstance(node, OperationalDriverNode):
        return inputs[0].quantity, available_at, lineage, None, None
    if isinstance(node, ExpressionFormulaNode):
        quantity = evaluate_formula(node.ast, {p.node_id: p.quantity for p in inputs})
        return quantity, available_at, lineage, node.formula_version, None
    if isinstance(node, FormulaNode):
        return _fold(node, inputs), available_at, lineage, node.formula_version, None
    if isinstance(node, AggregationNode):
        total = inputs[0].quantity
        for parent in inputs[1:]:
            total = total + parent.quantity
        return total, available_at, lineage, node.operator.value, None
    if isinstance(node, ValidationCheckNode):
        value, passed = _check(node, inputs)
        return Quantity(value, node.unit), available_at, lineage, node.check.value, passed
    if isinstance(node, ReportedFinancialOutputNode):
        quantum = node.quantum
        if quantum is None:
            if node.unit.currency is None:  # unreachable: the node requires a quantum otherwise
                raise UnitError(f"{node.node_id}: non-currency output without a quantum")
            quantum = minor_unit_quantum(node.unit.currency)
        return inputs[0].quantity.quantize(quantum), available_at, lineage, None, None
    raise ValueTypeError(f"unsupported node type {type(node).__name__}")  # pragma: no cover


def _iterate(
    snapshot: GraphSnapshot,
    group: IterationGroup,
    results: Mapping[str, CalcResult],
    cutoff: datetime,
    sink: TelemetrySink | None,
) -> tuple[dict[str, CalcResult], IterationRun]:
    graph = snapshot.graph
    external_ids = sorted(
        {
            ref
            for member in group.members
            for _, ref in graph.by_id[member].inputs()
            if ref not in group.members
        }
    )
    parent_ids = sorted(set(external_ids) | {seed for _, seed in group.seeds})
    parents = [results[node_id] for node_id in parent_ids]
    input_ids = tuple(dict.fromkeys(parent.result_id for parent in parents))
    available_at = max(parent.available_at for parent in parents)
    lineage = Lineage(Provenance.DERIVED, derived_from=input_ids)
    previous = {member: results[seed].quantity for member, seed in group.seeds}
    external = {node_id: results[node_id].quantity for node_id in external_ids}
    tolerances = dict(group.absolute_tolerances)
    emit(
        sink,
        "calc.iteration.started",
        group_id=group.group_id,
        algorithm=ITERATION_ALGORITHM,
        max_iterations=group.max_iterations,
        member_count=len(group.members),
    )
    completed = 0
    residuals: dict[str, Decimal] = {}
    try:
        for iteration in range(1, group.max_iterations + 1):
            inputs = {**external, **previous}
            current: dict[str, Quantity] = {}
            for member in group.members:
                node = graph.by_id[member]
                if isinstance(node, ExpressionFormulaNode):
                    current[member] = evaluate_formula(node.ast, inputs)
                else:
                    # Graph construction restricts group members to these two shapes.
                    assert isinstance(node, FormulaNode)
                    quantity = inputs[node.operands[0]]
                    for ref in node.operands[1:]:
                        rhs = inputs[ref]
                        if node.operator is Operator.ADD:
                            quantity = quantity + rhs
                        elif node.operator is Operator.SUB:
                            quantity = quantity - rhs
                        elif node.operator is Operator.MUL:
                            quantity = quantity * rhs
                        else:
                            quantity = quantity / rhs
                    current[member] = quantity
            completed = iteration
            converged = True
            for member in group.members:
                old, new = previous[member].value, current[member].value
                residual = CALC_CONTEXT.subtract(new, old).copy_abs()
                threshold = CALC_CONTEXT.add(
                    tolerances[member],
                    CALC_CONTEXT.multiply(
                        group.relative_tolerance, max(new.copy_abs(), old.copy_abs())
                    ),
                )
                residuals[member] = residual
                converged = converged and residual <= threshold
            if converged:
                break
            previous = current
        else:
            raise IterationConvergenceError(
                f"{group.group_id}: did not converge after {completed} sweeps",
                group_id=group.group_id,
                iterations=completed,
                residuals=dict(residuals),
            )
    except DecimalException as exc:
        error = FormulaError(
            "iteration convergence arithmetic failed",
            group_id=group.group_id,
            iterations=completed,
            operation=type(exc).__name__,
        )
        emit(
            sink,
            "calc.iteration.failed",
            group_id=group.group_id,
            algorithm=ITERATION_ALGORITHM,
            max_iterations=group.max_iterations,
            iterations=completed,
            error_code=error.code,
        )
        raise error from exc
    except CalculationEngineError as exc:
        exc.details.setdefault("group_id", group.group_id)
        emit(
            sink,
            "calc.iteration.failed",
            group_id=group.group_id,
            algorithm=ITERATION_ALGORITHM,
            max_iterations=group.max_iterations,
            iterations=completed,
            error_code=exc.code,
        )
        raise
    record = IterationRun(
        run_id="",
        policy=group,
        member_definitions=tuple((member, graph.definitions[member]) for member in group.members),
        dependencies=tuple(
            (member, tuple(ref for _, ref in graph.by_id[member].inputs()))
            for member in group.members
        ),
        seed_result_ids=tuple(
            (member, seed, results[seed].result_id) for member, seed in group.seeds
        ),
        external_result_ids=tuple(
            (node_id, results[node_id].result_id) for node_id in external_ids
        ),
        cutoff=cutoff,
        iterations=completed,
        values=tuple(
            (member, current[member], graph.by_id[member].period) for member in group.members
        ),
        residuals=tuple(sorted(residuals.items())),
    )
    record = replace(record, run_id=content_hash(record.payload()))
    outputs: dict[str, CalcResult] = {}
    for member in group.members:
        node = graph.by_id[member]
        assert isinstance(node, FormulaNode | ExpressionFormulaNode)
        outputs[member] = CalcResult(
            result_id=content_hash(
                {
                    "schema": "fel-calc-iterative-result/v1",
                    "run_id": record.run_id,
                    "node_id": member,
                }
            ),
            node_id=member,
            kind=node.kind,
            provenance=node.provenance,
            value=current[member].value,
            unit=node.unit,
            period=node.period,
            available_at=available_at,
            lineage=lineage,
            input_result_ids=input_ids,
            formula_version=node.formula_version,
            iteration_run_id=record.run_id,
        )
    emit(
        sink,
        "calc.iteration.completed",
        group_id=group.group_id,
        run_id=record.run_id,
        algorithm=ITERATION_ALGORITHM,
        max_iterations=group.max_iterations,
        iterations=completed,
    )
    return outputs, record


def evaluate(
    snapshot: GraphSnapshot, *, cutoff: datetime, sink: TelemetrySink | None = None
) -> EvaluationResult:
    if not isinstance(snapshot, GraphSnapshot):
        raise ValueTypeError("evaluate() takes a GraphSnapshot")
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        raise CutoffViolationError("cutoff must be a timezone-aware datetime")
    cutoff_utc = cutoff.astimezone(UTC)
    cutoff_key = json.dumps(cutoff_utc.isoformat())
    graph = snapshot.graph
    emit(
        sink,
        "calc.evaluate.started",
        snapshot_id=snapshot.snapshot_id,
        cutoff=cutoff_utc.isoformat(),
        node_count=len(graph),
        edge_count=len(graph.edges),
    )
    started = perf_counter()
    results: dict[str, CalcResult] = {}
    iteration_runs: dict[str, IterationRun] = {}
    failed: list[str] = []
    current = ""
    try:
        for step in graph.execution_plan:
            if isinstance(step, IterationGroup):
                current = step.members[0]
                group_results, record = _iterate(snapshot, step, results, cutoff_utc, sink)
                results.update(group_results)
                iteration_runs[record.run_id] = record
                continue
            node_id = step
            current = node_id
            node = graph.by_id[node_id]
            inputs = [results[ref] for _, ref in node.inputs()]
            quantity, available_at, lineage, version, passed = _compute(node, inputs, cutoff_utc)
            input_ids = tuple(parent.result_id for parent in inputs)
            material = (
                '{"cutoff":'
                + cutoff_key
                + ',"inputs":'
                + json.dumps(list(input_ids))
                + ',"node":'
                + graph.definitions[node_id]
                + ',"schema":"'
                + (
                    "fel-calc-result/v2"
                    if isinstance(node, ExpressionFormulaNode)
                    else RESULT_SCHEMA
                )
                + '"}'
            )
            results[node_id] = CalcResult(
                result_id=sha256_hex(material),
                node_id=node_id,
                kind=node.kind,
                provenance=node.provenance,
                value=quantity.value,
                unit=quantity.unit,
                period=node.period,
                available_at=available_at,
                lineage=lineage,
                input_result_ids=input_ids,
                formula_version=version,
                passed=passed,
            )
            if passed is False:
                failed.append(node_id)
    except CalculationEngineError as exc:
        exc.details.setdefault("node_id", current)
        emit(
            sink,
            "calc.evaluate.failed",
            snapshot_id=snapshot.snapshot_id,
            error_code=exc.code,
            node_id=exc.details["node_id"],
            duration_ms=int((perf_counter() - started) * 1000),
        )
        raise
    evaluation_id = content_hash(
        {
            "schema": ("fel-calc-evaluation/v2" if graph.uses_v2 else EVALUATION_SCHEMA),
            "snapshot_id": snapshot.snapshot_id,
            "cutoff": cutoff_utc,
            "results": [results[node_id].result_id for node_id in graph.order],
        }
    )
    duration_ms = int((perf_counter() - started) * 1000)
    emit(
        sink,
        "calc.evaluate.completed",
        snapshot_id=snapshot.snapshot_id,
        evaluation_id=evaluation_id,
        cutoff=cutoff_utc.isoformat(),
        node_count=len(graph),
        edge_count=len(graph.edges),
        result_count=len(results),
        failed_check_count=len(failed),
        duration_ms=duration_ms,
    )
    return EvaluationResult(
        evaluation_id=evaluation_id,
        snapshot_id=snapshot.snapshot_id,
        cutoff=cutoff_utc,
        order=graph.order,
        results=MappingProxyType(results),
        failed_checks=tuple(failed),
        iteration_runs=MappingProxyType(iteration_runs),
    )


__all__ = ["EVALUATION_SCHEMA", "RESULT_SCHEMA", "CalcResult", "EvaluationResult", "evaluate"]
