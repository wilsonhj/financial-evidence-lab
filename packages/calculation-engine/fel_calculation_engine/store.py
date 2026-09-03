"""Snapshot store Protocol with an in-memory implementation (T0402).

No M4 database tables exist yet (#197) and ``db/migrations`` is a shared path,
so persistence is a Protocol: the in-memory store is the reference behaviour a
later Postgres-backed store (a separate ``contract-change``) must reproduce —
content-hash verification on write, idempotent puts, parent-before-child.
"""

from __future__ import annotations

from typing import Protocol

from fel_calculation_engine.errors import SnapshotError
from fel_calculation_engine.snapshot import GraphSnapshot


class SnapshotStore(Protocol):
    def put(self, snapshot: GraphSnapshot) -> str:
        """Persist an immutable snapshot; returns its id. Idempotent for identical content."""

    def get(self, snapshot_id: str) -> GraphSnapshot: ...

    def lineage(self, snapshot_id: str) -> tuple[GraphSnapshot, ...]:
        """Root-first ancestry ending with the requested snapshot."""

    def versions(self, model_id: str) -> tuple[GraphSnapshot, ...]:
        """Every stored snapshot of a model, ordered by (version, snapshot_id)."""


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._by_id: dict[str, GraphSnapshot] = {}
        self._by_model: dict[str, list[str]] = {}

    def put(self, snapshot: GraphSnapshot) -> str:
        if not snapshot.verify():
            raise SnapshotError(
                "snapshot content does not match its id", snapshot_id=snapshot.snapshot_id
            )
        if snapshot.snapshot_id in self._by_id:
            return snapshot.snapshot_id
        if (
            snapshot.parent_snapshot_id is not None
            and snapshot.parent_snapshot_id not in self._by_id
        ):
            raise SnapshotError(
                "parent snapshot is not stored", parent_snapshot_id=snapshot.parent_snapshot_id
            )
        self._by_id[snapshot.snapshot_id] = snapshot
        self._by_model.setdefault(snapshot.model_id, []).append(snapshot.snapshot_id)
        return snapshot.snapshot_id

    def get(self, snapshot_id: str) -> GraphSnapshot:
        try:
            return self._by_id[snapshot_id]
        except KeyError as exc:
            raise SnapshotError(
                f"unknown snapshot {snapshot_id!r}", snapshot_id=snapshot_id
            ) from exc

    def lineage(self, snapshot_id: str) -> tuple[GraphSnapshot, ...]:
        chain: list[GraphSnapshot] = []
        current: str | None = snapshot_id
        while current is not None:
            snapshot = self.get(current)
            chain.append(snapshot)
            current = snapshot.parent_snapshot_id
        chain.reverse()
        return tuple(chain)

    def versions(self, model_id: str) -> tuple[GraphSnapshot, ...]:
        ids = self._by_model.get(model_id, [])
        return tuple(
            sorted((self._by_id[i] for i in ids), key=lambda s: (s.version, s.snapshot_id))
        )


__all__ = ["InMemorySnapshotStore", "SnapshotStore"]
