"""Extraction checkpoint verification, commits and usage audit."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.hashing import (
    hash_json,
)
from fel_workers.extraction.persist import UsageSnapshot
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.telemetry import emit
from fel_workers.extraction.types import (
    StageRecord,
)
from fel_workers.extraction.workflow_context import _ExecCtx
from fel_workers.redact import redact_error_text


def _is_recoverable(ctx: _ExecCtx, record: StageRecord) -> bool:
    """Reject a checkpoint that cannot hand back the output it claims.

    Two rejections, both fail-closed, both answered the same way: re-run the
    stage. That is always safe — a stage is idempotent by construction, keyed on
    ``input_hash`` — whereas trusting a checkpoint that is wrong about its own
    output is not.

    **Missing output.** ``output_hash`` non-null with ``output is None`` was the
    torn state a crash between the step commit and its ``step_completed`` event
    left behind, back when the event payload was the only carrier. Migration 0006
    puts the output on the step row in the same INSERT as its hash, under
    ``CHECK ((output IS NULL) = (output_hash IS NULL))``, so new rows cannot be
    torn. Rows written before 0006 on runs that have since gone terminal are
    unrepairable — 0004 forbids UPDATE on a terminal run and DELETE outright — so
    this branch is retained permanently as a legacy-row defence. Treating such a
    row as a completed stage skips it with zero model calls and lands the run
    ``succeeded`` + ``abstained=True`` with no proposals: silent data loss
    dressed up as a legitimate abstention.

    **Output that does not match its hash** (issue #158). ``output_hash`` is
    ``hash_json`` over the serialized output, so recomputing it is a complete
    check of the restored payload: any edit, truncation or substitution anywhere
    in the subtree changes it. Nothing else would catch a tampered or corrupted
    ``steps.output`` — ``_restore_output``'s ``text_hash`` check covers only
    ``assemble_evidence``'s span text, and the model-derived subtrees
    (``classification``, ``candidates``, ``raw_proposals``, ``normalized``) have
    no other content address at all. A mismatch would otherwise be laundered into
    proposal identity: ``raw_payload_hash`` and ``proposal_id_for`` are computed
    from the restored payload, so the run would emit self-consistent proposals
    that no longer describe what the stage actually produced.

    The rejection is reported as a ``step_failed`` event carrying
    ``error.code = 'checkpoint_rejected'``. The event vocabulary is frozen —
    ``ALLOWED_EVENT_TYPES`` mirrors 0004's ``event_type`` CHECK, which has no
    ``checkpoint_rejected`` member and would reject the insert — so the reason
    travels in the payload instead. See the operator runbook.
    """
    if record.output_hash is not None and record.output is None:
        _reject_checkpoint(
            ctx,
            record=record,
            reason="checkpoint_output_missing",
            message=(
                f"step {record.step_name} claims output_hash {record.output_hash} "
                "but stored no output"
            ),
        )
        return False
    if record.output is not None:
        actual = hash_json(serialize_stage_output(record.output))
        if actual != record.output_hash:
            _reject_checkpoint(
                ctx,
                record=record,
                reason="checkpoint_hash_mismatch",
                message=(
                    f"step {record.step_name} stored output hashing to {actual} "
                    f"under output_hash {record.output_hash}"
                ),
            )
            return False
    return True


def _reject_checkpoint(ctx: _ExecCtx, *, record: StageRecord, reason: str, message: str) -> None:
    """Record a refused checkpoint, then let the caller re-run the stage.

    Best-effort, like ``_record_stage_failure``: a store that is itself failing
    must not turn a recoverable re-run into a crash. The event type is
    ``step_failed`` because the vocabulary is frozen — see ``_is_recoverable``.
    """
    req = ctx.state.request
    reject_loaded = getattr(ctx.deps.checkpoint, "reject_loaded", None)
    if reject_loaded is not None:
        reject_loaded(
            run_id=req.run_id,
            org_id=req.org_id,
            workflow_version=req.workflow_version,
            record=record,
        )
    emit(
        "stage_checkpoint_rejected",
        run_id=req.run_id,
        step_name=record.step_name,
        input_hash=record.input_hash,
        output_hash=record.output_hash,
        reason=reason,
    )
    try:
        ctx.deps.events.append(
            org_id=req.org_id,
            run_id=req.run_id,
            event_type="step_failed",
            payload={
                "step_name": record.step_name,
                "input_hash": record.input_hash,
                "output_hash": record.output_hash,
                "error": {"code": "checkpoint_rejected", "message": message},
                "reason": reason,
                "action": "stage_re_executed",
            },
        )
    except Exception:  # pragma: no cover — never block the re-run on telemetry
        return


def _commit_stage(
    ctx: _ExecCtx, *, record: StageRecord, event_payload: dict[str, Any]
) -> StageRecord:
    """Commit a succeeded stage row and its ``step_completed`` event as one unit.

    Since ADR-0011 the stage's result is durable on the step row itself
    (``extraction_run_steps.output``, written in the same INSERT as
    ``output_hash``), so the event is no longer the carrier of anything a resume
    needs — it is telemetry. The transaction is kept anyway, for a narrower
    reason than the one it was written for: a crash between the two writes now
    costs an audit event rather than an extraction, and an audit trail with holes
    in it is still a defect. Stores that can do it atomically expose
    ``commit_succeeded_atomic``; the in-memory doubles have no durability
    boundary to straddle and fall back to the two-call form.
    """
    req = ctx.state.request
    atomic = getattr(ctx.deps.checkpoint, "commit_succeeded_atomic", None)
    if callable(atomic):
        committed: StageRecord = atomic(
            run_id=req.run_id,
            org_id=req.org_id,
            workflow_version=req.workflow_version,
            record=record,
            events=ctx.deps.events,
            event_payload=event_payload,
        )
        return committed
    committed = ctx.deps.checkpoint.commit_succeeded(
        run_id=req.run_id,
        org_id=req.org_id,
        workflow_version=req.workflow_version,
        record=record,
    )
    ctx.deps.events.append(
        org_id=req.org_id,
        run_id=req.run_id,
        event_type="step_completed",
        payload=event_payload,
    )
    return committed


def _record_stage_failure(
    ctx: _ExecCtx, *, step_name: str, input_hash: str, exc: BaseException
) -> None:
    """Write the failed step row and its ``step_failed`` event, then let the caller re-raise.

    Without this a failing stage leaves ``extraction_run_steps`` with no row and
    no error for the step that actually broke — the only signal is the run-level
    ``run_failed`` payload, so step-level diagnosis of a failed run is impossible.

    Every write here is best-effort and guarded: a store that is itself failing
    (the common case when a stage dies) must not replace the real exception with
    a bookkeeping one. The lease is checked first because a run whose lease is
    gone no longer owns these rows.
    """
    req = ctx.state.request
    code = getattr(exc, "code", None) or type(exc).__name__
    error = {"code": str(code), "message": redact_error_text(str(exc))}
    try:
        if not ctx.deps.lease_check():
            return
        record = StageRecord(
            step_name=step_name,
            attempt=1,
            status="failed",
            input_hash=input_hash,
            error=error,
        )
        commit_failed = getattr(ctx.deps.checkpoint, "commit_failed", None)
        if callable(commit_failed):
            commit_failed(
                run_id=req.run_id,
                org_id=req.org_id,
                workflow_version=req.workflow_version,
                record=record,
            )
            ctx.state.stages[step_name] = record
        ctx.deps.events.append(
            org_id=req.org_id,
            run_id=req.run_id,
            event_type="step_failed",
            payload={"step_name": step_name, "input_hash": input_hash, "error": error},
        )
        emit("step_failed", run_id=req.run_id, step_name=step_name, code=error["code"])
    except Exception:  # pragma: no cover — never mask the originating failure
        return


def _record_usage(ctx: _ExecCtx) -> None:
    """Persist accumulated usage and emit ``budget_updated``."""
    req = ctx.state.request
    usage = UsageSnapshot(
        calls_used=ctx.budget.calls_used,
        input_tokens_used=ctx.budget.input_tokens_used,
        output_tokens_used=ctx.budget.output_tokens_used,
        cost_usd=ctx.budget.cost_usd,
        wall_seconds_used=ctx.budget.elapsed_seconds(),
    )
    ctx.deps.persist.record_usage(run_id=req.run_id, org_id=req.org_id, usage=usage)
    ctx.deps.events.append(
        org_id=req.org_id,
        run_id=req.run_id,
        event_type="budget_updated",
        payload={
            "calls_used": usage.calls_used,
            "input_tokens_used": usage.input_tokens_used,
            "output_tokens_used": usage.output_tokens_used,
            "cost_usd": str(usage.cost_usd),
            "wall_seconds_used": usage.wall_seconds_used,
        },
    )
