"""Extraction workflow dependency protocols and execution context."""

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
