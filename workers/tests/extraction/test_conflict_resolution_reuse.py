"""A later run must not inherit an earlier run's conflict resolution (#60 review).

`extraction_conflicts` is keyed `UNIQUE (org_id, workspace_id, conflict_key)`
and `conflict_key` is a pure function of *what* the metric is — no run id, no
corpus version (`validate/duplicates.py::conflict_key_for`). So a rerun that
reproduces the same disagreement recomputes the same key, the upsert's
`ON CONFLICT DO NOTHING` skips, and the follow-up SELECT returns the EARLIER
row — including its `status`.

If that row was already `resolved`, the rerun's brand-new, never-reviewed
proposals get attached to a resolved group and the human's adjudication is
silently reused. Nothing sets the status back. The rows cannot be repaired
afterwards: 0004 forbids DELETE on `extraction_conflicts` and grants only
SELECT/INSERT on `extraction_conflict_members`.

Fixing the identity itself means putting a run scope in the UNIQUE constraint,
which is a frozen-migration change (`contract-change` + ADR). Until that
decision is made, the durable path fails closed rather than writing a record
that cannot be unwritten.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.persist import PostgresPersistStore
from fel_workers.extraction.types import ConflictDraft

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _store_returning(status: str, conflict_id: str) -> tuple[Any, list[tuple[str, Any]]]:
    """A stubbed connection whose existing conflict row carries ``status``."""
    executed: list[tuple[str, Any]] = []

    class _Conn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
            executed.append((sql, params))

            class _Result:
                def fetchone(self_inner) -> tuple[Any, ...] | None:  # noqa: N805
                    if "FROM extraction_conflicts" in sql:
                        return (conflict_id, status)
                    return None

            return _Result()

    return PostgresPersistStore(_Conn()), executed  # type: ignore[arg-type]


def _persist(store: PostgresPersistStore, key: str = "ck-rerun") -> Any:
    with patch(
        "fel_workers.extraction.persist.assert_workspace_ownership",
        lambda *a, **k: None,
    ):
        return store.persist_conflicts(
            org_id=str(uuid4()),
            workspace_id=str(uuid4()),
            drafts=[
                ConflictDraft(
                    conflict_key=key,
                    reason_codes=["value_disagreement"],
                    member_proposal_ids=[str(uuid4()), str(uuid4())],
                )
            ],
        )


def test_rerun_does_not_attach_members_to_a_resolved_conflict() -> None:
    """The resolved group must not silently absorb unreviewed proposals."""
    store, executed = _store_returning("resolved", str(uuid4()))

    with pytest.raises(StepFailed) as exc:
        _persist(store)

    assert "resolved" in str(exc.value)
    members = [sql for sql, _ in executed if "extraction_conflict_members" in sql]
    assert not members, "no member may be written into an adjudicated conflict group"


def test_rerun_does_not_attach_members_to_a_superseded_conflict() -> None:
    """`superseded` is equally terminal — 0004 allows open/resolved/superseded."""
    store, executed = _store_returning("superseded", str(uuid4()))

    with pytest.raises(StepFailed):
        _persist(store)

    assert not [sql for sql, _ in executed if "extraction_conflict_members" in sql]


def test_open_conflict_still_attaches_members() -> None:
    """Control: the ordinary path is untouched, so the guard is not vacuous."""
    conflict_id = str(uuid4())
    store, executed = _store_returning("open", conflict_id)

    out = _persist(store)

    assert out and out[0].id == conflict_id
    members = [(sql, p) for sql, p in executed if "extraction_conflict_members" in sql]
    assert len(members) == 2
    for _sql, params in members:
        assert params[0] == conflict_id
