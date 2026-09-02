"""``persist_proposals`` — the run's single durable write."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.context import ExecCtx
from fel_workers.extraction.errors import LeaseLost, StepFailed


def stage_persist(ctx: ExecCtx) -> dict[str, Any]:
    if not ctx.deps.lease_check():
        raise LeaseLost("queue lease lost before persist")
    state = ctx.state
    req = state.request
    # One transaction for proposals, their evidence and their conflicts. Written
    # separately these were three autocommitted groups, so a conflict failure —
    # 0004's `conflict_terminal` guard is the reachable trigger — left the
    # proposals durable with no conflict membership. Those orphans cannot be
    # repaired: once the run finalises `failed`, `fel_guard_extraction_proposal`
    # blocks moving them to `rejected` and DELETE is forbidden outright.
    persisted, conflicts = ctx.deps.persist.persist_outputs_atomic(
        run_id=req.run_id,
        org_id=req.org_id,
        workspace_id=req.workspace_id,
        proposals=state.validated,
        conflicts=state.conflicts,
        events=ctx.deps.events,
    )
    for draft in persisted:
        if draft.state != "needs_review":
            raise StepFailed("proposal escaped needs_review — auto-approve forbidden")
    return {"persisted": len(persisted), "conflicts": len(conflicts)}


__all__ = ["stage_persist"]
