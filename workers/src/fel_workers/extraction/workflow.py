"""Finite extraction workflow FSM (M3-101 / M3-102) with crash-resume."""

from __future__ import annotations

from typing import Any

from fel_ontology import load_saas_metrics
from fel_ontology.units import UNIT_POLICY_VERSION
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import (
    BudgetExceeded,
    Cancelled,
    ExtractionError,
    LeaseLost,
    ProviderRefused,
    StepFailed,
)
from fel_workers.extraction.hashing import (
    canonical_json,
    hash_json,
    stage_input_hash,
)
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.stages.assemble_evidence import (
    _stage_assemble_evidence as _stage_assemble_evidence,
)
from fel_workers.extraction.stages.detect_conflicts import (
    _stage_detect_conflicts as _stage_detect_conflicts,
)
from fel_workers.extraction.stages.model import _evidence_dicts as _evidence_dicts
from fel_workers.extraction.stages.model import _stage_model as _stage_model
from fel_workers.extraction.stages.normalize import _stage_normalize as _stage_normalize
from fel_workers.extraction.stages.persist_proposals import _stage_persist as _stage_persist
from fel_workers.extraction.stages.validate import _stage_validate as _stage_validate
from fel_workers.extraction.stages.validate_request import (
    _stage_validate_request as _stage_validate_request,
)
from fel_workers.extraction.stages.verify_citations import (
    _stage_verify_citations as _stage_verify_citations,
)
from fel_workers.extraction.telemetry import emit
from fel_workers.extraction.types import (
    MODE_STAGES,
    NORMALIZER_VERSION,
    RANGE_POLICY_VERSION,
    STAGE_ORDER,
    VALIDATOR_VERSION,
    WORKFLOW_VERSION,
    Role,
    StageRecord,
    WorkflowState,
)
from fel_workers.extraction.workflow_checkpoint import _commit_stage as _commit_stage
from fel_workers.extraction.workflow_checkpoint import _is_recoverable as _is_recoverable
from fel_workers.extraction.workflow_checkpoint import (
    _record_stage_failure as _record_stage_failure,
)
from fel_workers.extraction.workflow_checkpoint import _record_usage as _record_usage
from fel_workers.extraction.workflow_checkpoint import _reject_checkpoint as _reject_checkpoint
from fel_workers.extraction.workflow_codec import _restore_output as _restore_output
from fel_workers.extraction.workflow_codec import evidence_map as evidence_map
from fel_workers.extraction.workflow_context import CheckpointStore as CheckpointStore
from fel_workers.extraction.workflow_context import EventStore as EventStore
from fel_workers.extraction.workflow_context import PersistStore as PersistStore
from fel_workers.extraction.workflow_context import WorkflowDeps as WorkflowDeps
from fel_workers.extraction.workflow_context import _ExecCtx as _ExecCtx
from fel_workers.extraction.workflow_context import _ModelStepAudit as _ModelStepAudit


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
    ctx = _ExecCtx(state=state, deps=deps, budget=budget, ontology=ontology)
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
            if state.request.workflow_version != WORKFLOW_VERSION:
                raise StepFailed(f"unsupported workflow version: {state.request.workflow_version}")
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
                _record_usage(ctx)
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


def _mark_skipped(ctx: _ExecCtx, step_name: str) -> None:
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


def _boundary(ctx: _ExecCtx) -> None:
    if not ctx.deps.lease_check():
        raise LeaseLost("queue lease lost at stage boundary")
    if ctx.deps.cancel_check():
        raise Cancelled("run cancelled at stage boundary")
    if ctx.budget.elapsed_seconds() > ctx.budget.max_wall_seconds:
        raise BudgetExceeded(f"wall clock cap {ctx.budget.max_wall_seconds}s reached")


def _commit_fence(ctx: _ExecCtx, step_name: str) -> None:
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
    and rejected checkpoints can be repaired at that key. The fence stops a
    lease-less worker replacing the owner's checkpoint or appending events to
    a run it no longer owns.

    Raising here writes nothing and the owner re-runs the stage, which is
    idempotent by construction (keyed on ``input_hash``). The wall-clock cap is
    deliberately not re-checked: ``_boundary`` already enforces it at every stage
    start, and failing at the finish line would only discard completed work.
    """
    if not ctx.deps.lease_check():
        raise LeaseLost(f"queue lease lost before committing stage {step_name}")
    if ctx.deps.cancel_check():
        raise Cancelled(f"run cancelled before committing stage {step_name}")


def _run_stage(ctx: _ExecCtx, step_name: str) -> None:
    req = ctx.state.request
    stage_payload = _stage_input_payload(ctx.state, step_name)
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
        _restore_output(ctx.state, step_name, existing.output)
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


def _stage_input_payload(state: WorkflowState, step_name: str) -> Any:
    req = state.request
    if step_name == "validate_request":
        return {
            "run_id": req.run_id,
            "modes": list(req.modes),
            "input_hash": req.input_hash,
            "ontology_version": req.ontology_version,
        }
    if step_name == "assemble_evidence":
        return {"manifest": req.input_manifest, "corpus_version_id": req.corpus_version_id}
    if step_name == "classify":
        return {"evidence_hashes": [e.text_hash for e in state.evidence]}
    if step_name == "collect_candidates":
        return {"classification": state.classification}
    if step_name in MODE_STAGES.values():
        return {"candidates": state.candidates, "classification": state.classification}
    if step_name == "normalize":
        return {
            "raw_proposals": state.raw_proposals,
            "normalizer_version": NORMALIZER_VERSION,
            "unit_policy_version": UNIT_POLICY_VERSION,
            "range_policy_version": RANGE_POLICY_VERSION,
        }
    if step_name == "validate":
        return {
            "normalized": state.normalized,
            "validator_version": VALIDATOR_VERSION,
            "unit_policy_version": UNIT_POLICY_VERSION,
            "range_policy_version": RANGE_POLICY_VERSION,
        }
    if step_name == "verify_citations":
        return {"validated_count": len(state.validated)}
    if step_name == "detect_conflicts":
        return {"proposal_ids": [p.id for p in state.validated]}
    if step_name == "persist_proposals":
        return {
            "proposal_ids": [p.id for p in state.validated],
            "conflict_keys": [c.conflict_key for c in state.conflicts],
        }
    return {"step": step_name}


def _dispatch_stage(ctx: _ExecCtx, step_name: str) -> Any:
    state = ctx.state
    if step_name == "validate_request":
        return _stage_validate_request(state)
    if step_name == "assemble_evidence":
        return _stage_assemble_evidence(ctx)
    if step_name == "classify":
        return _stage_model(ctx, Role.CLASSIFIER, "classify")
    if step_name == "collect_candidates":
        return _stage_model(ctx, Role.FACT_CANDIDATES, "collect_candidates")
    if step_name == "extract_kpi":
        return _stage_model(ctx, Role.KPI, "extract_kpi")
    if step_name == "extract_guidance":
        return _stage_model(ctx, Role.GUIDANCE, "extract_guidance")
    if step_name == "extract_revenue_driver":
        return _stage_model(ctx, Role.DRIVER_MAPPER, "extract_revenue_driver")
    if step_name == "normalize":
        return _stage_normalize(state)
    if step_name == "validate":
        return _stage_validate(ctx)
    if step_name == "verify_citations":
        return _stage_verify_citations(state)
    if step_name == "detect_conflicts":
        return _stage_detect_conflicts(state)
    if step_name == "persist_proposals":
        return _stage_persist(ctx)
    raise StepFailed(f"unknown stage: {step_name}")


def _normalize_blocked_count(state: WorkflowState) -> int:
    """Payloads the normalizer rejected, read back from the normalize stage record."""
    record = state.stages.get("normalize")
    output = record.output if record is not None else None
    count = output.get("blocked_count") if isinstance(output, dict) else None
    return count if isinstance(count, int) else 0


def _finalize_success(ctx: _ExecCtx) -> None:
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
    "evidence_map",
    "run_extraction_workflow",
]
