"""The persist stage must use the atomic write, not two separate calls (#60 P1-3).

`persist_outputs_atomic` exists on both stores and wraps proposals, their
evidence and their conflicts in one transaction — but a method that nothing
calls protects nothing. This suite pins the *wiring*, which is the half that
was missing: `stages.persist` called `persist_proposals` and then
`persist_conflicts` with nothing between them, on an autocommit connection, so
a conflict failure left durable orphan proposals behind.

That failure mode is unrepairable: once the run finalises `failed`,
`fel_guard_extraction_proposal` blocks moving the orphans to `rejected` and
DELETE is forbidden, so a reviewer sees proposals the pipeline had grouped as
mutually contradictory presented as independent findings, with no way to
withdraw them.
"""

from __future__ import annotations

from typing import Any

import pytest

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.types import ConflictDraft, ProposalDraft

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _RecordingStore:
    """Persist store that records which write path the stage chose."""

    def __init__(self, *, fail_conflicts: bool = False) -> None:
        self.calls: list[str] = []
        self.persisted: list[ProposalDraft] = []
        self._fail_conflicts = fail_conflicts

    # -- the separate, non-atomic pair the stage must no longer use ----------
    def persist_proposals(
        self, *, run_id: str, org_id: str, workspace_id: str, drafts: list[ProposalDraft]
    ) -> list[ProposalDraft]:
        del run_id, org_id, workspace_id
        self.calls.append("persist_proposals")
        self.persisted.extend(drafts)
        return list(drafts)

    def persist_conflicts(
        self, *, org_id: str, workspace_id: str, drafts: list[ConflictDraft]
    ) -> list[ConflictDraft]:
        del org_id, workspace_id
        self.calls.append("persist_conflicts")
        if self._fail_conflicts:
            raise StepFailed("conflict terminal", code="conflict_terminal")
        return list(drafts)

    # -- the atomic path -----------------------------------------------------
    def persist_outputs_atomic(
        self,
        *,
        run_id: str,
        org_id: str,
        workspace_id: str,
        proposals: list[ProposalDraft],
        conflicts: list[ConflictDraft],
        events: Any,
    ) -> tuple[list[ProposalDraft], list[ConflictDraft]]:
        del workspace_id
        self.calls.append("persist_outputs_atomic")
        if self._fail_conflicts:
            # A real transaction rolls the proposals back with the conflicts.
            raise StepFailed("conflict terminal", code="conflict_terminal")
        self.persisted.extend(proposals)
        events.append(
            org_id=org_id,
            run_id=run_id,
            event_type="proposals_persisted",
            payload={"count": len(proposals), "conflicts": len(conflicts)},
        )
        return list(proposals), list(conflicts)


def _run_stage(store: _RecordingStore) -> Any:
    from fel_workers.extraction.context import ExecCtx, WorkflowDeps
    from fel_workers.extraction.events import MemoryEventStore
    from fel_workers.extraction.stages.persist import stage_persist
    from fel_workers.extraction.types import WorkflowState

    from .test_workflow import _evidence, _request

    state = WorkflowState(request=_request(), evidence=_evidence())
    state.validated = [
        ProposalDraft(
            kind="kpi",
            metric_id="arr",
            payload={"kind": "kpi", "metric_id": "arr"},
            raw_payload_hash="sha256:" + "a" * 64,
            definition_hash="sha256:" + "b" * 64,
            comparability_key={"key": None, "fields": []},
        )
    ]
    state.conflicts = []
    deps = WorkflowDeps(structured_llm=None, persist=store, events=MemoryEventStore())

    from fel_workers.extraction.budget import RunBudget
    from fel_workers.extraction.validate.pipeline import default_ontology

    ctx = ExecCtx(state=state, deps=deps, budget=RunBudget(), ontology=default_ontology())
    return stage_persist(ctx)


def test_persist_stage_uses_the_atomic_write() -> None:
    """The stage must call the transactional path, not the separate pair."""
    store = _RecordingStore()

    _run_stage(store)

    assert "persist_outputs_atomic" in store.calls, (
        "the persist stage still writes proposals and conflicts separately; "
        "a conflict failure would leave durable orphan proposals"
    )
    assert "persist_proposals" not in store.calls
    assert "persist_conflicts" not in store.calls


def test_conflict_failure_persists_no_proposals() -> None:
    """A failing conflict write must take the proposals down with it."""
    store = _RecordingStore(fail_conflicts=True)

    with pytest.raises(StepFailed):
        _run_stage(store)

    assert store.persisted == [], (
        "proposals were durable while the conflict write failed — the orphan "
        "state 0004 makes unrepairable"
    )
