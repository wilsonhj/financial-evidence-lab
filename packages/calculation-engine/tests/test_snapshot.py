"""Versioned, immutable, content-addressed graph snapshots and the store Protocol (T0402)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from _fixtures import assumption, formula, revenue_model, source

from fel_calculation_engine.errors import SnapshotError
from fel_calculation_engine.nodes import Operator
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.store import InMemorySnapshotStore, SnapshotStore


def test_snapshot_id_is_a_content_hash_independent_of_node_order() -> None:
    nodes = revenue_model()
    snap_a = GraphSnapshot.build("model-1", nodes)
    snap_b = GraphSnapshot.build("model-1", list(reversed(nodes)))
    assert snap_a.snapshot_id == snap_b.snapshot_id
    assert snap_a.snapshot_id.startswith("sha256:")
    assert snap_a == snap_b
    assert snap_a.version == 1 and snap_a.parent_snapshot_id is None
    assert [n.node_id for n in snap_a.nodes] == sorted(n.node_id for n in nodes)


def test_snapshot_id_changes_with_any_value_model_or_parent_change() -> None:
    base = GraphSnapshot.build("model-1", revenue_model())
    nodes = revenue_model()
    nodes[0] = dataclasses.replace(nodes[0], value=Decimal("19.98"))
    assert GraphSnapshot.build("model-1", nodes).snapshot_id != base.snapshot_id
    assert GraphSnapshot.build("model-2", revenue_model()).snapshot_id != base.snapshot_id
    child = base.derive(revenue_model())
    assert child.snapshot_id != base.snapshot_id
    assert child.parent_snapshot_id == base.snapshot_id
    assert child.version == 2
    assert child.model_id == "model-1"


def test_snapshot_is_immutable_and_verifiable() -> None:
    snap = GraphSnapshot.build("model-1", revenue_model())
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        snap.version = 9  # type: ignore[misc]
    assert snap.verify() is True
    forged = dataclasses.replace(snap, version=9)
    assert forged.verify() is False
    assert snap.graph.node("revenue").node_id == "revenue"
    assert snap.canonical_json() == GraphSnapshot.build("model-1", revenue_model()).canonical_json()


def test_derive_replaces_nodes_by_id_and_keeps_the_rest() -> None:
    base = GraphSnapshot.build("model-1", revenue_model())
    child = base.with_nodes([assumption("growth", "0.25")])
    assert child.graph.node("growth").value == Decimal("0.25")  # type: ignore[union-attr]
    assert child.graph.node("price") == base.graph.node("price")
    assert child.parent_snapshot_id == base.snapshot_id
    assert base.graph.node("growth").value == Decimal("0.10")  # type: ignore[union-attr]


def test_store_round_trips_and_is_idempotent() -> None:
    store: SnapshotStore = InMemorySnapshotStore()
    base = GraphSnapshot.build("model-1", revenue_model())
    assert store.put(base) == base.snapshot_id
    assert store.put(base) == base.snapshot_id
    assert store.get(base.snapshot_id) is base
    child = base.with_nodes([assumption("growth", "0.25")])
    store.put(child)
    assert [s.snapshot_id for s in store.lineage(child.snapshot_id)] == [
        base.snapshot_id,
        child.snapshot_id,
    ]
    assert [s.version for s in store.versions("model-1")] == [1, 2]
    assert store.versions("other") == ()


def test_store_fails_closed_on_tampering_unknown_ids_and_orphans() -> None:
    store = InMemorySnapshotStore()
    base = GraphSnapshot.build("model-1", revenue_model())
    with pytest.raises(SnapshotError):
        store.get(base.snapshot_id)
    forged = dataclasses.replace(base, version=3)
    with pytest.raises(SnapshotError):
        store.put(forged)
    orphan = base.with_nodes([assumption("growth", "0.3")])
    with pytest.raises(SnapshotError):
        store.put(orphan)  # parent never stored
    store.put(base)
    store.put(orphan)
    other_content = GraphSnapshot.build(
        "model-1", [source("x", "1"), source("y", "2"), formula("z", Operator.ADD, ("x", "y"))]
    )
    store.put(other_content)
    assert len(store.versions("model-1")) == 3
