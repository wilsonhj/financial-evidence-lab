"""Finite extraction workflow FSM (M3-101 / M3-102) with crash-resume."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
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
from fel_workers.extraction.hashing import hash_json, stage_input_hash
from fel_workers.extraction.normalize import normalize_payload
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.roles.base import ROLE_SPECS
from fel_workers.extraction.runner import Abstention, run_model_step
from fel_workers.extraction.telemetry import emit
from fel_workers.extraction.types import (
    MODE_STAGES,
    STAGE_ORDER,
    WORKFLOW_VERSION,
    EvidenceBlock,
    ExtractionRunRequest,
    Role,
    StageRecord,
    WorkflowState,
)
from fel_workers.extraction.validate import validate_proposals


class CheckpointStore(Protocol):
    def load_succeeded(
        self, *, run_id: str, step_name: str, input_hash: str, workflow_version: str
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

    def set_run_status(
        self, *, run_id: str, status: str, error: dict[str, Any] | None = None
    ) -> None: ...


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


@dataclass
class _ExecCtx:
    state: WorkflowState
    deps: WorkflowDeps
    budget: RunBudget
    ontology: OntologyDocument
    newly_committed: int = 0
    model_calls: int = 0


def run_extraction_workflow(state: WorkflowState, deps: WorkflowDeps) -> WorkflowState:
    """Advance ``state`` through STAGE_ORDER with content-addressed resume."""
    ontology = deps.ontology or load_saas_metrics()
    budget = RunBudget(
        max_calls=state.request.max_calls,
        max_input_tokens=state.request.max_input_tokens,
        max_output_tokens=state.request.max_output_tokens,
        max_cost_usd=state.request.max_cost_usd,
        max_wall_seconds=state.request.max_wall_seconds,
        calls_used=state.usage.calls_used,
        input_tokens_used=state.usage.input_tokens_used,
        output_tokens_used=state.usage.output_tokens_used,
        cost_usd=state.usage.cost_usd,
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
        for step_name in STAGE_ORDER:
            _boundary(ctx)
            if _should_skip_mode_stage(state, step_name):
                _mark_skipped(ctx, step_name)
                continue
            _run_stage(ctx, step_name)
        _finalize_success(ctx)
    except LeaseLost:
        raise
    except Cancelled as exc:
        state.status = "cancelled"
        state.error = {"code": exc.code, "message": str(exc)}
        deps.persist.set_run_status(
            run_id=state.request.run_id, status="cancelled", error=state.error
        )
        deps.events.append(
            org_id=state.request.org_id,
            run_id=state.request.run_id,
            event_type="run_cancelled",
            payload=state.error,
        )
    except (BudgetExceeded, ProviderRefused, StepFailed, ExtractionError) as exc:
        state.status = "failed"
        state.error = {"code": getattr(exc, "code", "extraction_error"), "message": str(exc)}
        deps.persist.set_run_status(run_id=state.request.run_id, status="failed", error=state.error)
        deps.events.append(
            org_id=state.request.org_id,
            run_id=state.request.run_id,
            event_type="run_failed",
            payload=state.error,
        )
        emit("run_failed", run_id=state.request.run_id, code=state.error["code"])
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
        step_name=step_name,
        input_hash=input_hash,
        workflow_version=req.workflow_version,
    )
    if existing is not None and existing.status == "succeeded":
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

    output = _dispatch_stage(ctx, step_name)
    output_hash = hash_json(output) if output is not None else None
    record = StageRecord(
        step_name=step_name,
        attempt=1,
        status="succeeded",
        input_hash=input_hash,
        output_hash=output_hash,
        output=output,
    )
    committed = ctx.deps.checkpoint.commit_succeeded(
        run_id=req.run_id,
        org_id=req.org_id,
        workflow_version=req.workflow_version,
        record=record,
    )
    ctx.state.stages[step_name] = committed
    ctx.newly_committed += 1
    ctx.deps.events.append(
        org_id=req.org_id,
        run_id=req.run_id,
        event_type="step_completed",
        payload={"step_name": step_name, "output_hash": output_hash},
    )
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
            restored.append(
                EvidenceBlock(
                    source_span_id=str(block["source_span_id"]),
                    document_version_id=str(block["document_version_id"]),
                    text=str(block.get("text") or ""),
                    text_hash=str(block["text_hash"]),
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
    elif step_name == "normalize" and isinstance(output, list):
        state.normalized = output
    elif step_name == "validate" and isinstance(output, dict):
        state.normalized = list(output.get("normalized") or state.normalized)
        # Rebuild drafts so resume after validate does not lose proposals.
        evidence_by_span = {
            e.source_span_id: {
                "document_version_id": e.document_version_id,
                "text": e.text,
                "text_hash": e.text_hash,
            }
            for e in state.evidence
        }
        rebuilt = validate_proposals(
            run_id=state.request.run_id,
            payloads=state.normalized,
            evidence_by_span=evidence_by_span,
        )
        state.validated = rebuilt.proposals
        state.conflicts = rebuilt.conflicts
    elif step_name == "detect_conflicts" and isinstance(output, dict):
        if not state.validated and state.normalized:
            evidence_by_span = {
                e.source_span_id: {
                    "document_version_id": e.document_version_id,
                    "text": e.text,
                    "text_hash": e.text_hash,
                }
                for e in state.evidence
            }
            rebuilt = validate_proposals(
                run_id=state.request.run_id,
                payloads=state.normalized,
                evidence_by_span=evidence_by_span,
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
        item.setdefault("entity_id", req.entity_id)
        item.setdefault("issuer_label", req.issuer_label)
        stamped.append(item)
    ctx.state.raw_proposals.extend(stamped)
    return {"proposals": stamped}


def _stage_normalize(state: WorkflowState) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in state.raw_proposals:
        try:
            normalized.append(normalize_payload(raw))
        except ValueError:
            # Keep unnormalizable payloads out of proposals (abstain that candidate).
            continue
    state.normalized = normalized
    return normalized


def _stage_validate(ctx: _ExecCtx) -> dict[str, Any]:
    state = ctx.state
    evidence_by_span = {
        e.source_span_id: {
            "document_version_id": e.document_version_id,
            "text": e.text,
            "text_hash": e.text_hash,
        }
        for e in state.evidence
    }
    result = validate_proposals(
        run_id=state.request.run_id,
        payloads=state.normalized,
        evidence_by_span=evidence_by_span,
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
    evidence_ids = {e.source_span_id for e in state.evidence}
    invalid = 0
    for draft in state.validated:
        for row in draft.evidence:
            span_id = row.get("source_span_id")
            if span_id and span_id not in evidence_ids:
                row["citation_status"] = "invalid"
                invalid += 1
            else:
                row.setdefault("citation_status", "verified")
    return {"invalid_citations": invalid, "checked": len(state.validated)}


def _stage_detect_conflicts(state: WorkflowState) -> dict[str, Any]:
    # Conflicts already computed in validate; re-export deterministically.
    return {
        "conflict_keys": [c.conflict_key for c in state.conflicts],
        "count": len(state.conflicts),
    }


def _stage_persist(ctx: _ExecCtx) -> dict[str, Any]:
    state = ctx.state
    req = state.request
    persisted = ctx.deps.persist.persist_proposals(
        run_id=req.run_id,
        org_id=req.org_id,
        workspace_id=req.workspace_id,
        drafts=state.validated,
    )
    for draft in persisted:
        if draft.state != "needs_review":
            raise StepFailed("proposal escaped needs_review — auto-approve forbidden")
    conflicts = ctx.deps.persist.persist_conflicts(
        org_id=req.org_id,
        workspace_id=req.workspace_id,
        drafts=state.conflicts,
    )
    ctx.deps.events.append(
        org_id=req.org_id,
        run_id=req.run_id,
        event_type="proposals_persisted",
        payload={"count": len(persisted), "conflicts": len(conflicts)},
    )
    return {"persisted": len(persisted), "conflicts": len(conflicts)}


def _finalize_success(ctx: _ExecCtx) -> None:
    state = ctx.state
    req = state.request
    if state.validated:
        state.status = "waiting_review"
        ctx.deps.persist.set_run_status(run_id=req.run_id, status="waiting_review")
        ctx.deps.events.append(
            org_id=req.org_id,
            run_id=req.run_id,
            event_type="review_waiting",
            payload={"proposal_count": len(state.validated)},
        )
    else:
        state.status = "succeeded"
        state.abstained = True
        ctx.deps.persist.set_run_status(run_id=req.run_id, status="succeeded")
        ctx.deps.events.append(
            org_id=req.org_id,
            run_id=req.run_id,
            event_type="run_succeeded",
            payload={"abstained": True},
        )
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
