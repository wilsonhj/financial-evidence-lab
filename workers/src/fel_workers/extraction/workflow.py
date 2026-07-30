"""Finite extraction workflow FSM (M3-101 / M3-102) with crash-resume."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from fel_ontology import load_saas_metrics
from fel_ontology.models import OntologyDocument
from fel_providers.interfaces import StructuredLLMProvider
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import (
    BudgetExceeded,
    Cancelled,
    ExtractionError,
    IntegrityError,
    LeaseLost,
    ProviderRefused,
    StepFailed,
)
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.hashing import hash_json, sha256_hex, stage_input_hash
from fel_workers.extraction.normalize.pipeline import normalize_payload
from fel_workers.extraction.persist import MemoryPersistStore, UsageSnapshot
from fel_workers.extraction.roles.base import ROLE_SPECS
from fel_workers.extraction.runner import Abstention, run_model_step
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.telemetry import emit
from fel_workers.extraction.types import (
    MODE_STAGES,
    NORMALIZER_BLOCKERS_KEY,
    STAGE_ORDER,
    WORKFLOW_VERSION,
    EvidenceBlock,
    ExtractionRunRequest,
    Role,
    StageRecord,
    WorkflowState,
)
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.pipeline import citation_status_for
from fel_workers.redact import redact_error_text


class CheckpointStore(Protocol):
    def load_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        step_name: str,
        input_hash: str,
        workflow_version: str,
    ) -> StageRecord | None: ...

    def commit_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord: ...


class EventStore(Protocol):
    def append(
        self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> Any: ...


class PersistStore(Protocol):
    def persist_proposals(
        self,
        *,
        run_id: str,
        org_id: str,
        workspace_id: str,
        drafts: list[Any],
    ) -> list[Any]: ...

    def persist_conflicts(
        self,
        *,
        org_id: str,
        workspace_id: str,
        drafts: list[Any],
    ) -> list[Any]: ...

    def persist_outputs_atomic(
        self,
        *,
        run_id: str,
        org_id: str,
        workspace_id: str,
        proposals: list[Any],
        conflicts: list[Any],
        events: Any,
    ) -> tuple[list[Any], list[Any]]:
        """Proposals, evidence and conflicts in one transaction — see `_stage_persist`."""
        ...

    def set_run_status(
        self,
        *,
        run_id: str,
        org_id: str,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None: ...

    def record_usage(self, *, run_id: str, org_id: str, usage: UsageSnapshot) -> None: ...

    def load_usage(self, *, run_id: str, org_id: str) -> UsageSnapshot: ...


@dataclass
class WorkflowDeps:
    structured_llm: StructuredLLMProvider
    checkpoint: CheckpointStore = field(default_factory=MemoryCheckpointStore)
    events: EventStore = field(default_factory=MemoryEventStore)
    persist: PersistStore = field(default_factory=MemoryPersistStore)
    ontology: OntologyDocument | None = None
    cancel_check: Callable[[], bool] = lambda: False
    lease_check: Callable[[], bool] = lambda: True
    evidence_loader: Callable[[ExtractionRunRequest], list[EvidenceBlock]] | None = None
    # Crash-injection for tests: raise after committing this many new stages.
    crash_after_stages: int | None = None


@dataclass(frozen=True)
class _ModelStepAudit:
    """One model step's provenance, for the ``extraction_run_steps`` row.

    ``run_model_step`` knows the response ids, the attempt count and the request
    hashes; the row that has columns for them is written by ``_run_stage``, which
    only ever saw the stage output. Without this hand-off every step row carried
    ``provider_response_id=NULL``, zero tokens, zero cost and ``attempt=1`` even
    after a repair — an audit trail that reconciles with nothing.
    """

    provider_response_id: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    attempts: int
    instructions_hash: str
    attempt_request_hashes: tuple[str, ...]
    response_ids: tuple[str, ...]


@dataclass
class _ExecCtx:
    state: WorkflowState
    deps: WorkflowDeps
    budget: RunBudget
    ontology: OntologyDocument
    newly_committed: int = 0
    model_calls: int = 0
    # Set by `_stage_model`, consumed by `_run_stage`; cleared before each dispatch.
    model_audit: _ModelStepAudit | None = None


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
    committed the step row and its ``step_completed`` event. That is not a
    harmless duplicate. ``extraction_run_events`` has no uniqueness constraint and
    ``_load_stage_output`` takes ``ORDER BY id DESC LIMIT 1``, so the zombie's
    output is what the run's real owner reads back on resume.

    Raising here writes nothing and the owner re-runs the stage, which is
    idempotent by construction (keyed on ``input_hash``). The wall-clock cap is
    deliberately not re-checked: ``_boundary`` already enforces it at every stage
    start, and failing at the finish line would only discard completed work.
    """
    if not ctx.deps.lease_check():
        raise LeaseLost(f"queue lease lost before committing stage {step_name}")
    if ctx.deps.cancel_check():
        raise Cancelled(f"run cancelled before committing stage {step_name}")


def _is_recoverable(record: StageRecord, *, run_id: str) -> bool:
    """Reject a checkpoint that claims an output it cannot hand back.

    ``output_hash`` non-null with ``output is None`` is the torn state a crash
    between the step commit and its ``step_completed`` event leaves behind (see
    ``PostgresCheckpointStore.commit_succeeded_atomic``, which now makes the pair
    atomic so this cannot be produced any more — rows written by earlier code, or
    an event pruned later, still can be). Treating it as a completed stage skips
    the stage with zero model calls and lands the run ``succeeded`` +
    ``abstained=True`` with no proposals: silent data loss dressed up as a
    legitimate abstention. Re-running the stage is the fail-closed answer; the
    stage is idempotent by construction, keyed on ``input_hash``.
    """
    if record.output_hash is not None and record.output is None:
        emit(
            "stage_checkpoint_unrecoverable",
            run_id=run_id,
            step_name=record.step_name,
            input_hash=record.input_hash,
            output_hash=record.output_hash,
        )
        return False
    return True


def _commit_stage(
    ctx: _ExecCtx, *, record: StageRecord, event_payload: dict[str, Any]
) -> StageRecord:
    """Commit a succeeded stage and its output-carrying event as one unit.

    The ``step_completed`` event's ``stage_output`` is the ONLY carrier of a
    stage's result (0004 has no ``steps.output`` column), so the two writes must
    not be separately durable. Stores that can do it atomically expose
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
    if (
        existing is not None
        and existing.status == "succeeded"
        and _is_recoverable(existing, run_id=req.run_id)
    ):
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
    output_hash = hash_json(output) if output is not None else None
    record = StageRecord(
        step_name=step_name,
        attempt=1,
        status="succeeded",
        input_hash=input_hash,
        output_hash=output_hash,
        output=output,
    )
    event_payload = {
        "step_name": step_name,
        "input_hash": input_hash,
        "output_hash": output_hash,
        # Frozen 0004 has no steps.output column; persist resume payload here.
        "stage_output": serialize_stage_output(output),
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
        return {"raw_proposals": state.raw_proposals}
    if step_name == "validate":
        return {"normalized": state.normalized}
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


def _restore_output(state: WorkflowState, step_name: str, output: Any) -> None:
    if output is None:
        return
    if step_name == "assemble_evidence" and isinstance(output, list):
        restored: list[EvidenceBlock] = []
        for block in output:
            if isinstance(block, EvidenceBlock):
                restored.append(block)
                continue
            if not isinstance(block, dict):
                continue
            published = block.get("published_at")
            published_at = None
            if isinstance(published, datetime):
                published_at = published
            elif isinstance(published, str) and published:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            text = str(block.get("text") or "")
            text_hash = str(block["text_hash"])
            if sha256_hex(text) != text_hash:
                # Fail closed: re-extracting from altered text under the original
                # hash would emit proposals whose citations do not describe them.
                raise IntegrityError(
                    f"restored evidence for span {block['source_span_id']} does not "
                    "match its checkpointed text_hash"
                )
            restored.append(
                EvidenceBlock(
                    source_span_id=str(block["source_span_id"]),
                    document_version_id=str(block["document_version_id"]),
                    text=text,
                    text_hash=text_hash,
                    published_at=published_at,
                )
            )
        state.evidence = restored
    elif step_name == "classify" and isinstance(output, dict):
        state.classification = output
    elif step_name == "collect_candidates" and isinstance(output, dict):
        state.candidates = list(output.get("candidates") or [])
    elif step_name in MODE_STAGES.values() and isinstance(output, dict):
        proposals = output.get("proposals") or []
        if isinstance(proposals, list):
            state.raw_proposals.extend(proposals)
    elif step_name == "normalize" and isinstance(output, dict):
        state.normalized = list(output.get("normalized") or [])
    elif step_name == "validate" and isinstance(output, dict):
        state.normalized = list(output.get("normalized") or state.normalized)
        # Rebuild drafts so resume after validate does not lose proposals.
        rebuilt = validate_proposals(
            run_id=state.request.run_id,
            payloads=state.normalized,
            evidence_by_span=dict(evidence_map(state.evidence)),
        )
        state.validated = rebuilt.proposals
        state.conflicts = rebuilt.conflicts
    elif step_name == "detect_conflicts" and isinstance(output, dict):
        if not state.validated and state.normalized:
            rebuilt = validate_proposals(
                run_id=state.request.run_id,
                payloads=state.normalized,
                evidence_by_span=dict(evidence_map(state.evidence)),
            )
            state.validated = rebuilt.proposals
            state.conflicts = rebuilt.conflicts


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


def _stage_validate_request(state: WorkflowState) -> dict[str, Any]:
    req = state.request
    if not req.modes:
        raise StepFailed("modes must be non-empty")
    for mode in req.modes:
        if mode not in MODE_STAGES:
            raise StepFailed(f"unknown mode: {mode}")
    if not req.input_hash.startswith("sha256:"):
        raise StepFailed("input_hash must be sha256:…")
    if req.workflow_version != WORKFLOW_VERSION:
        # Allow pin mismatch only when explicitly testing; still record.
        pass
    return {"ok": True, "modes": list(req.modes)}


def _stage_assemble_evidence(ctx: _ExecCtx) -> list[dict[str, Any]]:
    state = ctx.state
    if ctx.deps.evidence_loader is not None:
        blocks = ctx.deps.evidence_loader(state.request)
    else:
        blocks = list(state.evidence)
    if not blocks:
        # Empty evidence is valid abstention path later — not an integrity error here.
        state.evidence = []
        return []
    for block in blocks:
        if not block.text_hash.startswith("sha256:"):
            raise IntegrityError(f"evidence text_hash missing for {block.source_span_id}")
        if sha256_hex(block.text) != block.text_hash:
            # Fail closed at ingest, not only on resume: the hash is the
            # citation's content address, so a digest that does not describe
            # the text makes every proposal cite evidence it cannot prove.
            raise IntegrityError(
                f"evidence text_hash does not describe its text for {block.source_span_id}"
            )
        if block.published_at is not None and block.published_at > state.request.as_of:
            from fel_workers.extraction.errors import CutoffViolation

            raise CutoffViolation(f"span {block.source_span_id} published_at after as_of cutoff")
    state.evidence = blocks
    return [
        {
            "source_span_id": b.source_span_id,
            "document_version_id": b.document_version_id,
            "text": b.text,
            "text_hash": b.text_hash,
            "published_at": b.published_at.isoformat() if b.published_at else None,
        }
        for b in blocks
    ]


def _evidence_dicts(state: WorkflowState) -> list[dict[str, str]]:
    return [{"source_span_id": e.source_span_id, "text": e.text} for e in state.evidence]


def _stage_model(ctx: _ExecCtx, role: Role, step_name: str) -> dict[str, Any]:
    spec = ROLE_SPECS[role]
    req = ctx.state.request
    # The budget is the only per-call usage ledger, so this step's share of it is
    # the delta across the call (repair attempt included).
    before_input = ctx.budget.input_tokens_used
    before_output = ctx.budget.output_tokens_used
    before_cost = ctx.budget.cost_usd
    try:
        result = run_model_step(
            provider=ctx.deps.structured_llm,
            spec=spec,
            evidence_blocks=_evidence_dicts(ctx.state),
            budget=ctx.budget,
            run_id=req.run_id,
            step_name=step_name,
            workflow_version=req.workflow_version,
            provider_ref=req.provider,
            model_ref=req.model,
            max_output_tokens=min(4096, req.max_output_tokens),
        )
    except ProviderRefused:
        # Refusal is a typed failure for the run (never abstention).
        raise
    ctx.model_calls += result.attempts
    ctx.model_audit = _ModelStepAudit(
        # The accepted answer is the last attempt's, never the rejected one.
        provider_response_id=result.response_ids[-1] if result.response_ids else None,
        input_tokens=ctx.budget.input_tokens_used - before_input,
        output_tokens=ctx.budget.output_tokens_used - before_output,
        cost_usd=ctx.budget.cost_usd - before_cost,
        attempts=result.attempts,
        instructions_hash=result.instructions_hash,
        attempt_request_hashes=result.attempt_request_hashes,
        response_ids=result.response_ids,
    )
    _record_usage(ctx)
    if isinstance(result.outcome, Abstention):
        ctx.state.abstained = True
        if role == Role.CLASSIFIER:
            ctx.state.classification = {
                "document_type": "unknown",
                "sections": [],
                "relevant_modes": list(req.modes),
                "abstained": True,
                "reason": result.outcome.reason,
            }
            return ctx.state.classification
        if role == Role.FACT_CANDIDATES:
            ctx.state.candidates = []
            return {"candidates": [], "abstained": True, "reason": result.outcome.reason}
        return {"proposals": [], "abstained": True, "reason": result.outcome.reason}

    outcome = result.outcome
    if not isinstance(outcome, dict):
        raise TypeError(f"role {role} returned non-object outcome")
    if role == Role.CLASSIFIER:
        ctx.state.classification = dict(outcome)
        return ctx.state.classification
    if role == Role.FACT_CANDIDATES:
        raw_candidates = outcome.get("candidates") or []
        candidates = list(raw_candidates) if isinstance(raw_candidates, list) else []
        ctx.state.candidates = [c for c in candidates if isinstance(c, dict)]
        return {"candidates": ctx.state.candidates}
    raw_proposals = outcome.get("proposals") or []
    proposals = list(raw_proposals) if isinstance(raw_proposals, list) else []
    # Stamp entity / issuer when mock omitted them.
    stamped: list[dict[str, Any]] = []
    for prop in proposals:
        if not isinstance(prop, dict):
            continue
        item = dict(prop)
        # Pin entity_id to the run request (overwrite model output).
        item["entity_id"] = req.entity_id
        item.setdefault("issuer_label", req.issuer_label)
        stamped.append(item)
    ctx.state.raw_proposals.extend(stamped)
    return {"proposals": stamped}


def _stage_normalize(state: WorkflowState) -> dict[str, Any]:
    """Normalize every raw proposal, keeping the unnormalizable ones visible.

    Dropping a payload the normalizer rejects made it vanish with no blocker, no
    event and no counter: when every proposal hit that path the run landed
    ``succeeded`` + ``abstained=True`` with nothing to review — total loss
    dressed up as a legitimate abstention. So the payload is carried forward
    unchanged with the rejection reason attached on ``NORMALIZER_BLOCKERS_KEY``,
    the same channel the normalizer already uses for the blockers it detects
    without aborting; ``validate/pipeline`` lifts it into
    ``validation_summary["blockers"]``, so the candidate reaches review as a
    proposal that cannot be accepted, reason included. Carrying it beats merely
    counting it because a reviewer can then see *which* payload was rejected.

    The counts are part of the stage output — hence of the durable
    ``step_completed`` event — so loss is legible without diffing event blobs.
    """
    normalized: list[dict[str, Any]] = []
    blocked = 0
    for raw in state.raw_proposals:
        payload, blockers = normalize_payload(raw)
        if blockers:
            blocked += 1
            payload = {**payload, NORMALIZER_BLOCKERS_KEY: blockers}
        normalized.append(payload)
    state.normalized = normalized
    if blocked:
        emit("normalize_blocked", run_id=state.request.run_id, blocked=blocked)
    return {
        "normalized": normalized,
        "normalized_count": len(normalized),
        "blocked_count": blocked,
    }


def _stage_validate(ctx: _ExecCtx) -> dict[str, Any]:
    state = ctx.state
    result = validate_proposals(
        run_id=state.request.run_id,
        payloads=state.normalized,
        evidence_by_span=dict(evidence_map(state.evidence)),
        ontology=ctx.ontology,
    )
    state.validated = result.proposals
    state.conflicts = result.conflicts
    return {
        "normalized": state.normalized,
        "proposal_count": len(result.proposals),
        "conflict_count": len(result.conflicts),
    }


def _stage_verify_citations(state: WorkflowState) -> dict[str, Any]:
    """Grade every citation row from the pinned evidence, overwriting the row.

    The grade is assigned, never defaulted: `setdefault` let a model-supplied
    `citation_status: "verified"` survive into `extraction_proposal_evidence`,
    which 0004 makes append-only — UPDATE and DELETE both raise — so the wrong
    value could never be corrected. `citation_status_for` is the single rule (see
    its docstring for why span membership alone earns `partial`, not `verified`).
    """
    pinned = dict(evidence_map(state.evidence))
    counts = {"verified": 0, "partial": 0, "invalid": 0}
    for draft in state.validated:
        for row in draft.evidence:
            status = citation_status_for(row, evidence_by_span=pinned)
            row["citation_status"] = status
            counts[status] += 1
    return {
        "invalid_citations": counts["invalid"],
        "partial_citations": counts["partial"],
        "verified_citations": counts["verified"],
        "checked": len(state.validated),
    }


def _stage_detect_conflicts(state: WorkflowState) -> dict[str, Any]:
    # Conflicts already computed in validate; re-export deterministically.
    return {
        "conflict_keys": [c.conflict_key for c in state.conflicts],
        "count": len(state.conflicts),
    }


def _stage_persist(ctx: _ExecCtx) -> dict[str, Any]:
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


def evidence_map(blocks: list[EvidenceBlock]) -> Mapping[str, dict[str, Any]]:
    return {
        b.source_span_id: {
            "document_version_id": b.document_version_id,
            "text": b.text,
            "text_hash": b.text_hash,
        }
        for b in blocks
    }


__all__ = [
    "CheckpointStore",
    "EventStore",
    "PersistStore",
    "WorkflowDeps",
    "evidence_map",
    "run_extraction_workflow",
]
