"""Dependency edges, structural validation, and cycle detection (T0402, FR-MOD-001).

Edges are *derived* from :meth:`Node.inputs` so the lineage a node declares and
the visual graph are the same data. ``ModelGraph.build`` fails closed on
duplicate ids, dangling references and cycles, and type-checks every derived
node against its inputs (unit algebra, period kind, rollup quarters, override
targets) so a graph that builds is a graph that can be evaluated.
"""

from __future__ import annotations

import dataclasses
import heapq
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from fel_calculation_engine.canonical import canonical_json
from fel_calculation_engine.errors import (
    CycleError,
    GraphError,
    MissingInputError,
    PeriodError,
    ScenarioError,
    UnitError,
)
from fel_calculation_engine.nodes import (
    AggregationNode,
    AggregationOp,
    FormulaNode,
    Node,
    NodeKind,
    OperationalDriverNode,
    Operator,
    ReportedFinancialOutputNode,
    ScenarioOverrideNode,
    ValidationCheckNode,
)
from fel_calculation_engine.periods import FiscalYear
from fel_calculation_engine.units import Unit

#: Node kinds a scenario override may shadow (an override of an override layers scenarios).
_OVERRIDABLE = frozenset(
    {NodeKind.ANALYST_ASSUMPTION, NodeKind.OPERATIONAL_DRIVER, NodeKind.SCENARIO_OVERRIDE}
)


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    role: str


@dataclass(frozen=True, slots=True)
class ModelGraph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    order: tuple[str, ...]
    by_id: Mapping[str, Node] = field(compare=False, repr=False)
    _dependencies: Mapping[str, tuple[str, ...]] = field(compare=False, repr=False)
    _dependents: Mapping[str, tuple[str, ...]] = field(compare=False, repr=False)
    #: Canonical JSON of each node *definition* (label blanked — presentation only), computed
    #: once per graph so evaluation can content-address results without re-encoding nodes.
    definitions: Mapping[str, str] = field(compare=False, repr=False)

    @classmethod
    def build(cls, nodes: Iterable[Node]) -> ModelGraph:
        by_id: dict[str, Node] = {}
        for node in nodes:
            if not isinstance(node, Node):
                raise GraphError(f"not a Node: {node!r}")
            if node.node_id in by_id:
                raise GraphError(f"duplicate node id {node.node_id!r}", node_id=node.node_id)
            by_id[node.node_id] = node
        sorted_nodes = tuple(by_id[node_id] for node_id in sorted(by_id))

        edges: list[Edge] = []
        dependencies: dict[str, tuple[str, ...]] = {}
        dependents: dict[str, list[str]] = {node_id: [] for node_id in by_id}
        for node in sorted_nodes:
            deps: list[str] = []
            for role, ref in node.inputs():
                if ref not in by_id:
                    raise MissingInputError(
                        f"{node.node_id}: input {ref!r} ({role}) is not in the graph",
                        node_id=node.node_id,
                        missing=ref,
                        role=role,
                    )
                edges.append(Edge(source=ref, target=node.node_id, role=role))
                deps.append(ref)
                dependents[ref].append(node.node_id)
            dependencies[node.node_id] = tuple(deps)

        order = _topological_order(by_id, dependencies, dependents)
        _check_types(by_id, order)
        definitions = {
            node.node_id: canonical_json(dataclasses.replace(node, label=""))
            for node in sorted_nodes
        }
        return cls(
            nodes=sorted_nodes,
            edges=tuple(edges),
            order=order,
            by_id=MappingProxyType(by_id),
            _dependencies=MappingProxyType(dependencies),
            _dependents=MappingProxyType({k: tuple(v) for k, v in dependents.items()}),
            definitions=MappingProxyType(definitions),
        )

    def node(self, node_id: str) -> Node:
        try:
            return self.by_id[node_id]
        except KeyError as exc:
            raise MissingInputError(f"unknown node {node_id!r}", missing=node_id) from exc

    def dependencies(self, node_id: str) -> tuple[str, ...]:
        self.node(node_id)
        return self._dependencies[node_id]

    def dependents(self, node_id: str) -> tuple[str, ...]:
        self.node(node_id)
        return self._dependents[node_id]

    def __len__(self) -> int:
        return len(self.nodes)


def _topological_order(
    by_id: Mapping[str, Node],
    dependencies: Mapping[str, tuple[str, ...]],
    dependents: Mapping[str, list[str]],
) -> tuple[str, ...]:
    """Kahn's algorithm with a min-heap so the order is deterministic for a given graph."""
    indegree = {node_id: len(deps) for node_id, deps in dependencies.items()}
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        order.append(node_id)
        for dependent in dependents[node_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)
    if len(order) != len(by_id):
        remaining = {node_id for node_id, degree in indegree.items() if degree > 0}
        raise CycleError(_find_cycle(remaining, dependencies))
    return tuple(order)


def _find_cycle(
    remaining: set[str], dependencies: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """Return one concrete cycle ``(n0, n1, ..., n0)`` among the unresolved nodes."""
    stack: list[str] = []
    on_stack: dict[str, int] = {}
    visited: set[str] = set()

    def walk(node_id: str) -> tuple[str, ...] | None:
        visited.add(node_id)
        on_stack[node_id] = len(stack)
        stack.append(node_id)
        for dep in dependencies[node_id]:
            if dep not in remaining:
                continue
            if dep in on_stack:
                return tuple(stack[on_stack[dep] :]) + (dep,)
            if dep not in visited:
                found = walk(dep)
                if found is not None:
                    return found
        stack.pop()
        del on_stack[node_id]
        return None

    for start in sorted(remaining):
        if start not in visited:
            cycle = walk(start)
            if cycle is not None:
                return cycle
    raise CycleError(tuple(sorted(remaining)))  # pragma: no cover - unresolved but acyclic


def _formula_unit(node: FormulaNode, operands: list[Node]) -> Unit:
    unit = operands[0].unit
    for operand in operands[1:]:
        if node.operator is Operator.ADD:
            unit = unit.add(operand.unit)
        elif node.operator is Operator.SUB:
            unit = unit.sub(operand.unit)
        elif node.operator is Operator.MUL:
            unit = unit.mul(operand.unit)
        else:
            unit = unit.div(operand.unit)
    return unit


def _require_unit(node: Node, computed: Unit) -> None:
    if computed != node.unit:
        raise UnitError(
            f"{node.node_id}: declared {node.unit.key()} but inputs compute {computed.key()}",
            node_id=node.node_id,
            declared=node.unit.key(),
            computed=computed.key(),
        )


def _require_same_period(node: Node, other: Node) -> None:
    if other.period != node.period:
        raise PeriodError(
            f"{node.node_id}: input {other.node_id} is {other.period.key()}, "
            f"expected {node.period.key()}",
            node_id=node.node_id,
        )


def _require_period_kind(node: Node, other: Node) -> None:
    if other.period.kind is not node.period.kind:
        raise PeriodError(
            f"{node.node_id}: input {other.node_id} is a {other.period.kind.value}, "
            f"expected a {node.period.kind.value}",
            node_id=node.node_id,
        )


def _check_types(by_id: Mapping[str, Node], order: tuple[str, ...]) -> None:
    for node_id in order:
        node = by_id[node_id]
        inputs = [by_id[ref] for _, ref in node.inputs()]
        if isinstance(node, OperationalDriverNode | ReportedFinancialOutputNode):
            _require_unit(node, inputs[0].unit)
            _require_same_period(node, inputs[0])
        elif isinstance(node, FormulaNode):
            for operand in inputs:
                _require_period_kind(node, operand)
            _require_unit(node, _formula_unit(node, inputs))
        elif isinstance(node, AggregationNode):
            for operand in inputs:
                _require_unit(node, operand.unit)
            if node.operator is AggregationOp.SUM:
                for operand in inputs:
                    _require_same_period(node, operand)
            else:
                year = node.period
                if not isinstance(year, FiscalYear):  # pragma: no cover - enforced by the node
                    raise PeriodError(f"{node.node_id}: rollup output must be a fiscal year")
                expected = set(year.quarters())
                actual = {operand.period for operand in inputs}
                if actual != expected:
                    raise PeriodError(
                        f"{node.node_id}: rollup needs exactly {year.key()} Q1..Q4, "
                        f"got {sorted(p.key() for p in actual)}",
                        node_id=node.node_id,
                    )
        elif isinstance(node, ValidationCheckNode):
            for operand in inputs:
                _require_unit(node, operand.unit)
                _require_period_kind(node, operand)
        elif isinstance(node, ScenarioOverrideNode):
            target = inputs[0]
            if target.kind not in _OVERRIDABLE:
                raise ScenarioError(
                    f"{node.node_id}: overrides may target assumptions, drivers or "
                    f"earlier overrides, not {target.kind.value}",
                    node_id=node.node_id,
                    target=target.node_id,
                )
            _require_unit(node, target.unit)
            _require_same_period(node, target)


OVERRIDABLE_KINDS = _OVERRIDABLE

__all__ = ["OVERRIDABLE_KINDS", "Edge", "ModelGraph"]
