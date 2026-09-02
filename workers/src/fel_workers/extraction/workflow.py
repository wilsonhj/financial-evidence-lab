"""Finite extraction workflow FSM (M3-101 / M3-102) with crash-resume.

This module is the control loop and nothing else: stage fencing, the
content-addressed checkpoint lookup and commit, stage-failure recording,
dispatch, and terminal handling. The twelve stage bodies live in
``fel_workers.extraction.stages``; the payload shaping that feeds the
checkpoint key lives in ``fel_workers.extraction.stages.io``; the injected
dependencies and per-run context live in ``fel_workers.extraction.context``.

``STAGE_ORDER``, ``WORKFLOW_VERSION`` and every hash computed here are part of
the durable checkpoint key ``(run_id, step_name, input_hash,
workflow_version)``. ``workers/tests/extraction/test_checkpoint_hash_golden.py``
pins them so a refactor cannot move them silently.
"""

from __future__ import annotations

from typing import Any

from fel_ontology import load_saas_metrics
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.context import (
    CheckpointStore,
    EventStore,
    ExecCtx,
    PersistStore,
    WorkflowDeps,
    record_usage,
)
from fel_workers.extraction.errors import (
    BudgetExceeded,
    Cancelled,
    ExtractionError,
    LeaseLost,
    ProviderRefused,
    StepFailed,
)
from fel_workers.extraction.hashing import canonical_json, hash_json, stage_input_hash
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.stages import (
    restore_output,
    stage_assemble_evidence,
    stage_detect_conflicts,
    stage_input_payload,
    stage_model,
    stage_normalize,
    stage_persist,
    stage_validate,
    stage_validate_request,
    stage_verify_citations,
)
from fel_workers.extraction.telemetry import emit
from fel_workers.extraction.types import (
    MODE_STAGES,
    STAGE_ORDER,
    WORKFLOW_VERSION,
    Role,
    StageRecord,
    WorkflowState,
)
from fel_workers.redact import redact_error_text


def run_extraction_workflow(state: WorkflowState, deps: WorkflowDeps) -> WorkflowState:
    """Advance ``state`` through STAGE_ORDER with content-addressed resume."""
    ontology = deps.ontology or load_saas_metrics()
    # Caps bound the run, not one queue attempt: earlier attempts may be ahead of
    # the in-memory usage this attempt was handed.
    carried = deps.persist.load_usage(run_id=state.request.run_id, org_id=state.request.org_id)
    budget = RunBudget(
        max_calls=state.request.max_calls,
        max_input_tokens=state.request.max_input_tokens,
        max_output_tokens=state.request.max_output_tokens,
        max_cost_usd=state.request.max_cost_usd,
        max_wall_seconds=state.request.max_wall_seconds,
        calls_used=max(state.usage.calls_used, carried.calls_used),
        input_tokens_used=max(state.usage.input_tokens_used, carried.input_tokens_used),
        output_tokens_used=max(state.usage.output_tokens_used, carried.output_tokens_used),
        cost_usd=max(state.usage.cost_usd, carried.cost_usd),
        wall_seconds_used=carried.wall_seconds_used,
    )
    ctx = ExecCtx(state=state, deps=deps, budget=budget, ontology=ontology)
    state.status = "running"
    deps.events.append(
        org_id=state.request.org_id,
        run_id=state.request.run_id,
        event_type="run_started",
        payload={"workflow_version": WORKFLOW_VERSION},
    )
    emit("run_started", run_id=state.request.run_id)

    try:
        try:
            for step_name in STAGE_ORDER:
                _boundary(ctx)
                if _should_skip_mode_stage(state, step_name):
                    _mark_skipped(ctx, step_name)
                    continue
                _run_stage(ctx, step_name)
        finally:
            # Flush the run's usage so a requeue resumes from it, before any
            # terminal status write — frozen 0004 refuses to mutate a run row
            # that already reached a terminal status. A lost lease writes nothing.
            if deps.lease_check():
                record_usage(ctx)
        _finalize_success(ctx)
    except LeaseLost:
        raise
    except Cancelled as exc:
        if not deps.lease_check():
            raise LeaseLost("queue lease lost before cancelled status write") from exc
        state.status = "cancelled"
        state.error = {"code": exc.code, "message": str(exc)}
        # Append BEFORE the status write: 0004's fel_assert_extraction_run_open
        # rejects any child insert once the run row is terminal, so writing the
        # status first loses the event and masks `exc` with the guard error.
        deps.events.append(
            org_id=state.request.org_id,
            run_id=state.request.run_id,
            event_type="run_cancelled",
            payload=state.error,
        )
        deps.persist.set_run_status(
            run_id=state.request.run_id,
            org_id=state.request.org_id,
            status="cancelled",
            error=state.error,
        )
    except (BudgetExceeded, ProviderRefused, StepFailed, ExtractionError) as exc:
        if not deps.lease_check():
            raise LeaseLost("queue lease lost before failed status write") from exc
        state.status = "failed"
        state.error = {"code": getattr(exc, "code", "extraction_error"), "message": str(exc)}
        # Append before the terminal status write — see the run_cancelled note.
        deps.events.append(
            org_id=state.request.org_id,
            run_id=state.request.run_id,
            event_type="run_failed",
            payload=state.error,
        )
        deps.persist.set_run_status(
            run_id=state.request.run_id,
            org_id=state.request.org_id,
            status="failed",
            error=state.error,
        )
        emit("run_failed", run_id=state.request.run_id, code=state.error["code"])
    except Exception as exc:
        # Untyped escape (bad role outcome, malformed checkpoint, …): land the
        # run row so a crashed run is never mistaken for an in-flight one, then
        # re-raise so the traceback surfaces and the queue still fails the job.
        if not deps.lease_check():
            raise LeaseLost("queue lease lost before failed status write") from exc
        state.status = "failed"
        state.error = {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}
        # Append before the terminal status write — see the run_cancelled note.
        # Getting this backwards masked `exc` with the guard's own error, which
        # defeats the re-raise below.
        deps.events.append(
            org_id=state.request.org_id,
            run_id=state.request.run_id,
            event_type="run_failed",
            payload=state.error,
        )
        deps.persist.set_run_status(
            run_id=state.request.run_id,
            org_id=state.request.org_id,
            status="failed",
            error=state.error,
        )
        emit("run_failed", run_id=state.request.run_id, code=state.error["code"])
        raise
    finally:
        state.usage.calls_used = budget.calls_used
        state.usage.input_tokens_used = budget.input_tokens_used
        state.usage.output_tokens_used = budget.output_tokens_used
        state.usage.cost_usd = budget.cost_usd
    return state


def _should_skip_mode_stage(state: WorkflowState, step_name: str) -> bool:
    for mode, stage in MODE_STAGES.items():
        if step_name == stage and mode not in state.request.modes:
            return True
    return False


def _mark_skipped(ctx: ExecCtx, step_name: str) -> None:
    req = ctx.state.request
    input_hash = stage_input_hash(
        run_id=req.run_id,
        step_name=step_name,
        payload={"skipped": True, "modes": list(req.modes)},
        workflow_version=req.workflow_version,
    )
    ctx.state.stages[step_name] = StageRecord(
        step_name=step_name,
        attempt=1,
        status="skipped",
        input_hash=input_hash,
        output_hash=None,
    )


def _boundary(ctx: ExecCtx) -> None:
    if not ctx.deps.lease_check():
        raise LeaseLost("queue lease lost at stage boundary")
    if ctx.deps.cancel_check():
        raise Cancelled("run cancelled at stage boundary")
    if ctx.budget.elapsed_seconds() > ctx.budget.max_wall_seconds:
        raise BudgetExceeded(f"wall clock cap {ctx.budget.max_wall_seconds}s reached")


def _commit_fence(ctx: ExecCtx, step_name: str) -> None:
    """Re-fence between a stage's work and its durable write.

    ``_boundary`` runs before the stage, so everything after it — the model call
    above all — was unfenced: a worker whose lease expired mid-``classify`` still
    committed the step row and its ``step_completed`` event.

    That used to be worse than a duplicate. While the checkpoint lived in the
    event payload, ``extraction_run_events`` had no uniqueness constraint and the
    hydration read ``ORDER BY id DESC LIMIT 1``, so the zombie's output was what
    the run's real owner read back on resume. Since ADR-0011 the output lives on
    the step row, whose success key is the partial unique index
    ``(run_id, step_name, input_hash, workflow_version) WHERE status='succeeded'``
    and whose INSERT is ``ON CONFLICT DO NOTHING`` — a zombie's write now loses
    the race instead of winning it. The fence is still worth keeping: it stops
    the zombie writing at all, and it is the only thing that stops a lease-less
    worker appending events to a run it no longer owns.

    Raising here writes nothing and the owner re-runs the stage, which is
    idempotent by construction (keyed on ``input_hash``). The wall-clock cap is
    deliberately not re-checked: ``_boundary`` already enforces it at every stage
    start, and failing at the finish line would only discard completed work.
    """
    if not ctx.deps.lease_check():
        raise LeaseLost(f"queue lease lost before committing stage {step_name}")
    if ctx.deps.cancel_check():
        raise Cancelled(f"run cancelled before committing stage {step_name}")


def _is_recoverable(ctx: ExecCtx, record: StageRecord) -> bool:
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
    ``steps.output`` — ``stages.io.restore_output``'s ``text_hash`` check covers
    only ``assemble_evidence``'s span text, and the model-derived subtrees
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


def _reject_checkpoint(ctx: ExecCtx, *, record: StageRecord, reason: str, message: str) -> None:
    """Record a refused checkpoint, then let the caller re-run the stage.

    Best-effort, like ``_record_stage_failure``: a store that is itself failing
    must not turn a recoverable re-run into a crash. The event type is
    ``step_failed`` because the vocabulary is frozen — see ``_is_recoverable``.
    """
    req = ctx.state.request
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
    ctx: ExecCtx, *, record: StageRecord, event_payload: dict[str, Any]
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
    ctx: ExecCtx, *, step_name: str, input_hash: str, exc: BaseException
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


def _run_stage(ctx: ExecCtx, step_name: str) -> None:
    req = ctx.state.request
    stage_payload = stage_input_payload(ctx.state, step_name)
    input_hash = stage_input_hash(
        run_id=req.run_id,
        step_name=step_name,
        payload=stage_payload,
        workflow_version=req.workflow_version,
    )
    existing = ctx.deps.checkpoint.load_succeeded(
        run_id=req.run_id,
        org_id=req.org_id,
        step_name=step_name,
        input_hash=input_hash,
        workflow_version=req.workflow_version,
    )
    if existing is not None and existing.status == "succeeded" and _is_recoverable(ctx, existing):
        ctx.state.stages[step_name] = existing
        restore_output(ctx.state, step_name, existing.output)
        emit(
            "stage_resumed",
            run_id=req.run_id,
            step_name=step_name,
            input_hash=input_hash,
        )
        return

    ctx.deps.events.append(
        org_id=req.org_id,
        run_id=req.run_id,
        event_type="step_started",
        payload={"step_name": step_name, "input_hash": input_hash},
    )
    emit("step_started", run_id=req.run_id, step_name=step_name)

    ctx.model_audit = None
    try:
        output = _dispatch_stage(ctx, step_name)
    except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised unchanged
        _record_stage_failure(ctx, step_name=step_name, input_hash=input_hash, exc=exc)
        raise
    # The stored form IS the hashed form: `output_hash` is computed over exactly
    # the value that lands in `extraction_run_steps.output`, so a resume can
    # re-verify the row it read back (`_is_recoverable`, issue #158). Hashing the
    # pre-serialization object instead would produce a digest nothing durable
    # could ever be checked against.
    serialized = serialize_stage_output(output)
    output_hash = hash_json(serialized) if output is not None else None
    record = StageRecord(
        step_name=step_name,
        attempt=1,
        status="succeeded",
        input_hash=input_hash,
        output_hash=output_hash,
        output=serialized,
    )
    # Metadata only — no stage output, no source text (ADR-0011). The output is
    # on the step row; this event says a step finished and names its hashes.
    event_payload: dict[str, Any] = {
        "step_name": step_name,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "output_size_bytes": len(canonical_json(serialized)) if output is not None else 0,
    }
    audit = ctx.model_audit
    if audit is not None:
        record.attempt = audit.attempts
        record.provider_response_id = audit.provider_response_id
        record.input_tokens = audit.input_tokens
        record.output_tokens = audit.output_tokens
        record.cost_usd = audit.cost_usd
        # 0004 has no column for the instructions / per-attempt request hashes,
        # and migrations are frozen — the event payload is their only home.
        event_payload["model_step"] = {
            "attempts": audit.attempts,
            "instructions_hash": audit.instructions_hash,
            "attempt_request_hashes": list(audit.attempt_request_hashes),
            "provider_response_ids": list(audit.response_ids),
        }
    _commit_fence(ctx, step_name)
    ctx.state.stages[step_name] = _commit_stage(ctx, record=record, event_payload=event_payload)
    ctx.newly_committed += 1
    if (
        ctx.deps.crash_after_stages is not None
        and ctx.newly_committed >= ctx.deps.crash_after_stages
    ):
        raise RuntimeError(f"injected crash after stage {step_name}")


def _dispatch_stage(ctx: ExecCtx, step_name: str) -> Any:
    state = ctx.state
    if step_name == "validate_request":
        return stage_validate_request(state)
    if step_name == "assemble_evidence":
        return stage_assemble_evidence(ctx)
    if step_name == "classify":
        return stage_model(ctx, Role.CLASSIFIER, "classify")
    if step_name == "collect_candidates":
        return stage_model(ctx, Role.FACT_CANDIDATES, "collect_candidates")
    if step_name == "extract_kpi":
        return stage_model(ctx, Role.KPI, "extract_kpi")
    if step_name == "extract_guidance":
        return stage_model(ctx, Role.GUIDANCE, "extract_guidance")
    if step_name == "extract_revenue_driver":
        return stage_model(ctx, Role.DRIVER_MAPPER, "extract_revenue_driver")
    if step_name == "normalize":
        return stage_normalize(state)
    if step_name == "validate":
        return stage_validate(ctx)
    if step_name == "verify_citations":
        return stage_verify_citations(state)
    if step_name == "detect_conflicts":
        return stage_detect_conflicts(state)
    if step_name == "persist_proposals":
        return stage_persist(ctx)
    raise StepFailed(f"unknown stage: {step_name}")


def _normalize_blocked_count(state: WorkflowState) -> int:
    """Payloads the normalizer rejected, read back from the normalize stage record."""
    record = state.stages.get("normalize")
    output = record.output if record is not None else None
    count = output.get("blocked_count") if isinstance(output, dict) else None
    return count if isinstance(count, int) else 0


def _finalize_success(ctx: ExecCtx) -> None:
    if not ctx.deps.lease_check():
        raise LeaseLost("queue lease lost before finalize")
    state = ctx.state
    req = state.request
    if state.validated:
        state.status = "waiting_review"
        ctx.deps.persist.set_run_status(
            run_id=req.run_id, org_id=req.org_id, status="waiting_review"
        )
        ctx.deps.events.append(
            org_id=req.org_id,
            run_id=req.run_id,
            event_type="review_waiting",
            payload={"proposal_count": len(state.validated)},
        )
    else:
        state.status = "succeeded"
        state.abstained = True
        # Append before the terminal status write — see the run_cancelled note.
        # `waiting_review` above is non-terminal, so only this branch trips the
        # guard, which is why the happy path never surfaced it.
        ctx.deps.events.append(
            org_id=req.org_id,
            run_id=req.run_id,
            event_type="run_succeeded",
            payload={
                "abstained": True,
                # A real abstention reports 0 here; anything higher means the
                # normalizer rejected payloads, so the empty review queue is loss.
                "normalize_blocked_count": _normalize_blocked_count(state),
            },
        )
        ctx.deps.persist.set_run_status(run_id=req.run_id, org_id=req.org_id, status="succeeded")
    emit("run_finished", run_id=req.run_id, status=state.status)


__all__ = [
    "CheckpointStore",
    "EventStore",
    "PersistStore",
    "WorkflowDeps",
    "run_extraction_workflow",
]
