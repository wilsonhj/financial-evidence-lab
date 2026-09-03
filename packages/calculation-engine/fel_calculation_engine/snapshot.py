"""Versioned, immutable, content-addressed graph snapshots (T0402, FR-MOD-001, spec §11).

A snapshot is the unit of reproducibility: ``snapshot_id`` is the SHA-256 of
the typed canonical JSON of (model id, version, parent id, scenario id, every
node). Deriving a new version never mutates the parent — it builds a new
object whose ``parent_snapshot_id`` links back, so lineage is a hash chain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from fel_calculation_engine.canonical import canonical_json, content_hash
from fel_calculation_engine.errors import SnapshotError
from fel_calculation_engine.graph import ModelGraph
from fel_calculation_engine.nodes import Node
from fel_calculation_engine.values import require_safe_id


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    snapshot_id: str
    model_id: str
    version: int
    parent_snapshot_id: str | None
    scenario_id: str | None
    graph: ModelGraph = field(compare=False, repr=False)

    @property
    def nodes(self) -> tuple[Node, ...]:
        return self.graph.nodes

    @classmethod
    def build(
        cls,
        model_id: str,
        nodes: Iterable[Node],
        *,
        parent: GraphSnapshot | None = None,
        scenario_id: str | None = None,
    ) -> GraphSnapshot:
        require_safe_id(model_id, "model_id", SnapshotError)
        if scenario_id is not None:
            require_safe_id(scenario_id, "scenario_id", SnapshotError)
        if parent is not None and parent.model_id != model_id:
            raise SnapshotError("a snapshot cannot derive from another model's snapshot")
        graph = ModelGraph.build(nodes)
        version = 1 if parent is None else parent.version + 1
        parent_id = None if parent is None else parent.snapshot_id
        payload = _payload(model_id, version, parent_id, scenario_id, graph.nodes)
        return cls(
            snapshot_id=content_hash(payload),
            model_id=model_id,
            version=version,
            parent_snapshot_id=parent_id,
            scenario_id=scenario_id,
            graph=graph,
        )

    def derive(self, nodes: Iterable[Node], *, scenario_id: str | None = None) -> GraphSnapshot:
        """A new version of this model with a full replacement node set."""
        return GraphSnapshot.build(self.model_id, nodes, parent=self, scenario_id=scenario_id)

    def with_nodes(
        self, replacements: Iterable[Node], *, scenario_id: str | None = None
    ) -> GraphSnapshot:
        """A new version replacing (or adding) the given nodes by id; everything else is kept."""
        merged = {node.node_id: node for node in self.graph.nodes}
        for node in replacements:
            merged[node.node_id] = node
        return self.derive(merged.values(), scenario_id=scenario_id)

    def payload(self) -> dict[str, Any]:
        return _payload(
            self.model_id,
            self.version,
            self.parent_snapshot_id,
            self.scenario_id,
            self.graph.nodes,
        )

    def canonical_json(self) -> str:
        return canonical_json(self.payload())

    def verify(self) -> bool:
        return content_hash(self.payload()) == self.snapshot_id


def _payload(
    model_id: str,
    version: int,
    parent_snapshot_id: str | None,
    scenario_id: str | None,
    nodes: tuple[Node, ...],
) -> dict[str, Any]:
    return {
        "schema": "fel-calc-snapshot/v1",
        "model_id": model_id,
        "version": version,
        "parent_snapshot_id": parent_snapshot_id,
        "scenario_id": scenario_id,
        "nodes": list(nodes),
    }


__all__ = ["GraphSnapshot"]
