"""Sparse scenario layers over a base snapshot (T0403 groundwork for FR-MOD-003).

A :class:`Scenario` is an immutable, sparse set of ``{node_id: Decimal}``
overrides. ``apply_scenario`` never mutates the base: it derives a child
snapshot in which each override becomes a ``ScenarioOverrideNode`` shadowing
the *effective* target (so scenarios layer), and every consumer of that target
is re-pointed at the override. The original node stays in the graph — the
override's ``overrides`` edge records what was shadowed, and unaffected
sub-graphs keep identical result ids.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fel_calculation_engine.errors import ScenarioError
from fel_calculation_engine.graph import OVERRIDABLE_KINDS, ModelGraph
from fel_calculation_engine.nodes import (
    AggregationNode,
    FormulaNode,
    Node,
    NodeKind,
    OperationalDriverNode,
    ReportedFinancialOutputNode,
    ScenarioOverrideNode,
    ValidationCheckNode,
)
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.telemetry import TelemetrySink, emit
from fel_calculation_engine.values import require_decimal, require_safe_id


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    label: str
    overrides: tuple[tuple[str, Decimal], ...]
    as_of: datetime

    def __post_init__(self) -> None:
        require_safe_id(self.scenario_id, "scenario_id", ScenarioError)
        if not isinstance(self.label, str):
            raise ScenarioError("label must be a string")
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ScenarioError("as_of must be a timezone-aware datetime")
        if not self.overrides:
            raise ScenarioError("a scenario must override at least one node")
        keys = [key for key, _ in self.overrides]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise ScenarioError("overrides must be sorted by node id and unique")
        for key, value in self.overrides:
            require_safe_id(key, "override target", ScenarioError)
            require_decimal(value, f"override {key}")

    @classmethod
    def of(
        cls, scenario_id: str, label: str, overrides: Mapping[str, Decimal], *, as_of: datetime
    ) -> Scenario:
        return cls(
            scenario_id=scenario_id,
            label=label,
            overrides=tuple(sorted(overrides.items())),
            as_of=as_of,
        )


def _effective(graph: ModelGraph, node_id: str) -> str:
    """Follow the chain of overrides already shadowing ``node_id`` to its tail."""
    current = node_id
    while True:
        shadows = [
            dep
            for dep in graph.dependents(current)
            if graph.by_id[dep].kind is NodeKind.SCENARIO_OVERRIDE
            and graph.by_id[dep].inputs() == (("overrides", current),)
        ]
        if not shadows:
            return current
        if len(shadows) > 1:  # pragma: no cover - a snapshot never holds two shadows of one node
            raise ScenarioError(f"{current} is shadowed by more than one override")
        current = shadows[0]


def _rewire(node: Node, old: str, new: str) -> Node:
    def swap(refs: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(new if ref == old else ref for ref in refs)

    if isinstance(node, OperationalDriverNode):
        return dataclasses.replace(node, seed=new)
    if isinstance(node, FormulaNode | AggregationNode | ValidationCheckNode):
        return dataclasses.replace(node, operands=swap(node.operands))
    if isinstance(node, ReportedFinancialOutputNode):
        return dataclasses.replace(node, source=new)
    raise ScenarioError(f"{node.node_id}: cannot re-point a {node.kind.value} node")


def apply_scenario(
    base: GraphSnapshot, scenario: Scenario, *, sink: TelemetrySink | None = None
) -> GraphSnapshot:
    graph = base.graph
    nodes: dict[str, Node] = {node.node_id: node for node in graph.nodes}
    for target_id, value in scenario.overrides:
        target = graph.node(target_id)
        if target.kind not in OVERRIDABLE_KINDS or target.kind is NodeKind.SCENARIO_OVERRIDE:
            raise ScenarioError(
                f"{target_id}: only assumptions and drivers can be overridden, "
                f"not {target.kind.value}",
                target=target_id,
            )
        effective_id = _effective(graph, target_id)
        override_id = f"{target_id}--{scenario.scenario_id}"
        if override_id in nodes:
            raise ScenarioError(
                f"{override_id}: scenario {scenario.scenario_id!r} already overrides {target_id}",
                target=target_id,
            )
        nodes[override_id] = ScenarioOverrideNode(
            node_id=override_id,
            label=f"{scenario.label}: {target.label}",
            unit=target.unit,
            period=target.period,
            value=value,
            as_of=scenario.as_of,
            target=effective_id,
            scenario_id=scenario.scenario_id,
            assumption_id=f"{scenario.scenario_id}:{target_id}",
        )
        for dependent_id in graph.dependents(effective_id):
            dependent = nodes[dependent_id]
            if dependent.kind is NodeKind.SCENARIO_OVERRIDE:
                continue
            nodes[dependent_id] = _rewire(dependent, effective_id, override_id)
    child = base.derive(nodes.values(), scenario_id=scenario.scenario_id)
    emit(
        sink,
        "calc.scenario.applied",
        base_snapshot_id=base.snapshot_id,
        snapshot_id=child.snapshot_id,
        scenario_id=scenario.scenario_id,
        override_count=len(scenario.overrides),
        node_count=len(child.graph),
    )
    return child


__all__ = ["Scenario", "apply_scenario"]
