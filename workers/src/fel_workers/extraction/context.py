"""Execution context shared by the workflow FSM and its stage bodies.

The store protocols, the injected dependencies and the per-run execution
context live here rather than in ``workflow.py`` so that
``fel_workers.extraction.stages`` can depend on them without importing the
control loop that dispatches it — the loop imports the stages, so the reverse
edge would be a cycle.

Nothing here computes a hash or decides control flow; it is the wiring the
stages and the loop both need. ``WorkflowDeps`` is re-exported from
``workflow`` and remains the public spelling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from fel_ontology.models import OntologyDocument
from fel_providers.interfaces import StructuredLLMProvider
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.persist import MemoryPersistStore, UsageSnapshot
from fel_workers.extraction.types import (
    EvidenceBlock,
    ExtractionRunRequest,
    StageRecord,
    WorkflowState,
)


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
        """Proposals, evidence and conflicts in one transaction — see ``stages.persist``."""
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
class ModelStepAudit:
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
class ExecCtx:
    state: WorkflowState
    deps: WorkflowDeps
    budget: RunBudget
    ontology: OntologyDocument
    newly_committed: int = 0
    model_calls: int = 0
    # Set by `stages.model`, consumed by `_run_stage`; cleared before each dispatch.
    model_audit: ModelStepAudit | None = None


def record_usage(ctx: ExecCtx) -> None:
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


__all__ = [
    "CheckpointStore",
    "EventStore",
    "ExecCtx",
    "ModelStepAudit",
    "PersistStore",
    "WorkflowDeps",
    "record_usage",
]
