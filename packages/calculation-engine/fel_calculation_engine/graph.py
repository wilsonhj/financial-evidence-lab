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
    IterationPolicyError,
    MissingInputError,
    PeriodError,
    ScenarioError,
    UnitError,
)
from fel_calculation_engine.formulas import infer_formula_unit
from fel_calculation_engine.iteration import IterationGroup
from fel_calculation_engine.nodes import (
    AggregationNode,
    AggregationOp,
    ExpressionFormulaNode,
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

    iteration_groups: tuple[IterationGroup, ...] = ()
    execution_plan: tuple[str | IterationGroup, ...] = ()

    @property
    def uses_v2(self) -> bool:
        return bool(self.iteration_groups) or any(
            isinstance(node, ExpressionFormulaNode) for node in self.nodes
        )

    @classmethod
    def build(
        cls,
        nodes: Iterable[Node],
        *,
        iteration_groups: Iterable[IterationGroup] = (),
    ) -> ModelGraph:
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

        groups = tuple(iteration_groups)
        if any(type(group) is not IterationGroup for group in groups):
            raise IterationPolicyError("iteration_groups must contain IterationGroup policies")
        groups = tuple(sorted(groups, key=lambda group: group.group_id))
        if groups:
            plan = _iteration_plan(by_id, dependencies, dependents, groups)
            order = tuple(
                member
                for step in plan
                for member in (step.members if isinstance(step, IterationGroup) else (step,))
            )
            for group in groups:
                for member, seed in group.seeds:
                    edges.append(Edge(seed, member, "iteration_seed"))
                    dependencies[member] = tuple(dict.fromkeys((*dependencies[member], seed)))
                    if member not in dependents[seed]:
                        dependents[seed].append(member)
        else:
            order = _topological_order(by_id, dependencies, dependents)
            plan = tuple(order)
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
            iteration_groups=groups,
            execution_plan=plan,
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


def _components(
    dependencies: Mapping[str, tuple[str, ...]],
    dependents: Mapping[str, list[str]],
) -> tuple[tuple[str, ...], ...]:
    """Iterative Kosaraju traversal, bounded by graph size rather than Python recursion."""
    visited: set[str] = set()
    finished: list[str] = []
    for start in sorted(dependencies):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, 0)]
        while stack:
            node_id, cursor = stack[-1]
            deps = dependencies[node_id]
            if cursor == len(deps):
                finished.append(node_id)
                stack.pop()
            else:
                stack[-1] = (node_id, cursor + 1)
                dep = deps[cursor]
                if dep not in visited:
                    visited.add(dep)
                    stack.append((dep, 0))
    visited.clear()
    components: list[tuple[str, ...]] = []
    for start in reversed(finished):
        if start in visited:
            continue
        members: list[str] = []
        pending = [start]
        visited.add(start)
        while pending:
            node_id = pending.pop()
            members.append(node_id)
            for dependent in dependents[node_id]:
                if dependent not in visited:
                    visited.add(dependent)
                    pending.append(dependent)
        components.append(tuple(sorted(members)))
    return tuple(components)


def _iteration_plan(
    by_id: Mapping[str, Node],
    dependencies: Mapping[str, tuple[str, ...]],
    dependents: Mapping[str, list[str]],
    groups: tuple[IterationGroup, ...],
) -> tuple[str | IterationGroup, ...]:
    components = _components(dependencies, dependents)
    cyclic = {
        members
        for members in components
        if len(members) > 1 or members[0] in dependencies[members[0]]
    }
    declared: dict[tuple[str, ...], IterationGroup] = {}
    group_ids: set[str] = set()
    for group in groups:
        if group.group_id in group_ids or group.members in declared:
            raise IterationPolicyError("duplicate iteration group", group_id=group.group_id)
        group_ids.add(group.group_id)
        if group.members not in cyclic:
            raise IterationPolicyError(
                "group must match exactly one cyclic SCC", group_id=group.group_id
            )
        member_set = set(group.members)
        for member, seed in group.seeds:
            node = by_id[member]
            if not isinstance(node, FormulaNode | ExpressionFormulaNode):
                raise IterationPolicyError(
                    "only arithmetic formula nodes may iterate",
                    group_id=group.group_id,
                    node_id=member,
                )
            if seed not in by_id:
                raise MissingInputError("missing iteration seed", missing=seed, node_id=member)
            if seed in member_set:
                raise IterationPolicyError(
                    "iteration seeds must be external", group_id=group.group_id
                )
            _require_unit(node, by_id[seed].unit)
            _require_same_period(node, by_id[seed])
        declared[group.members] = group
    missing = cyclic - declared.keys()
    if missing:
        raise CycleError(_find_cycle(set(min(missing)), dependencies))
    component_of = {member: members[0] for members in components for member in members}
    prerequisites: dict[str, tuple[str, ...]] = {}
    successors: dict[str, list[str]] = {members[0]: [] for members in components}
    steps: dict[str, str | IterationGroup] = {}
    for members in components:
        key = members[0]
        parents = {
            component_of[ref]
            for member in members
            for ref in dependencies[member]
            if component_of[ref] != key
        }
        if members in declared:
            group = declared[members]
            parents.update(component_of[seed] for _, seed in group.seeds)
            steps[key] = group
        else:
            steps[key] = key
        prerequisites[key] = tuple(sorted(parents))
        for parent in parents:
            successors[parent].append(key)
    try:
        order = _topological_order({key: by_id[key] for key in steps}, prerequisites, successors)
    except CycleError as exc:
        raise IterationPolicyError(
            "seed prerequisites create an execution cycle", cycle=exc.cycle
        ) from exc
    return tuple(steps[key] for key in order)


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
    """Return one concrete cycle ``(n0, n1, ..., n0)`` among the unresolved nodes.

    Iterative on purpose. The recursive form recursed once per node on the path,
    so a cycle longer than the interpreter's recursion limit raised a bare
    ``RecursionError`` instead of ``CycleError`` — in a package whose stated
    target is 5,000-node graphs. That escapes ``except CalculationEngineError``
    and every ``code``-based classification, so a large cyclic model failed as an
    interpreter error rather than a modelling one. Detection was never the
    problem (Kahn's algorithm upstream is correct); only this reporter was.
    """
    visited: set[str] = set()

    for start in sorted(remaining):
        if start in visited:
            continue
        # (node, index of the next dependency to examine) — an explicit stack in
        # place of the call stack.
        stack: list[tuple[str, int]] = [(start, 0)]
        on_stack: dict[str, int] = {start: 0}
        visited.add(start)

        while stack:
            node_id, cursor = stack[-1]
            deps = dependencies[node_id]
            advanced = False

            while cursor < len(deps):
                dep = deps[cursor]
                cursor += 1
                if dep not in remaining:
                    continue
                if dep in on_stack:
                    stack[-1] = (node_id, cursor)
                    return tuple(entry for entry, _ in stack[on_stack[dep] :]) + (dep,)
                if dep not in visited:
                    stack[-1] = (node_id, cursor)
                    visited.add(dep)
                    on_stack[dep] = len(stack)
                    stack.append((dep, 0))
                    advanced = True
                    break

            if not advanced:
                stack[-1] = (node_id, cursor)
                if cursor >= len(deps):
                    del on_stack[node_id]
                    stack.pop()

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
        elif isinstance(node, ExpressionFormulaNode):
            for operand in inputs:
                _require_period_kind(node, operand)
            _require_unit(node, infer_formula_unit(node.ast, {p.node_id: p.unit for p in inputs}))
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
