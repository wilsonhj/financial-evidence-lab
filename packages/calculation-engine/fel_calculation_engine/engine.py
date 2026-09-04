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
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from types import MappingProxyType

from fel_calculation_engine.canonical import content_hash, sha256_hex
from fel_calculation_engine.errors import (
    CalculationEngineError,
    CutoffViolationError,
    MissingInputError,
    UnitError,
    ValueTypeError,
)
from fel_calculation_engine.nodes import (
    AggregationNode,
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
from fel_calculation_engine.periods import FiscalPeriod
from fel_calculation_engine.rounding import minor_unit_quantum
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.telemetry import TelemetrySink, emit
from fel_calculation_engine.units import Unit
from fel_calculation_engine.values import Lineage, Provenance, Quantity, require_decimal

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
    failed: list[str] = []
    current = ""
    try:
        for node_id in graph.order:
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
                + RESULT_SCHEMA
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
            "schema": EVALUATION_SCHEMA,
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
    )


__all__ = ["EVALUATION_SCHEMA", "RESULT_SCHEMA", "CalcResult", "EvaluationResult", "evaluate"]
