"""Shared types for the bounded extraction workflow (M3-101)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

ExtractionMode = Literal["kpi", "guidance", "revenue_driver"]
RunStatus = Literal["queued", "running", "waiting_review", "succeeded", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "cancelled"]
ProposalState = Literal["proposed", "needs_review", "accepted", "rejected", "superseded"]

WORKFLOW_VERSION = "extraction-workflow/v1"
NORMALIZER_VERSION = "normalize/v1"
VALIDATOR_VERSION = "validate/v1"

STAGE_ORDER: tuple[str, ...] = (
    "validate_request",
    "assemble_evidence",
    "classify",
    "collect_candidates",
    "extract_kpi",
    "extract_guidance",
    "extract_revenue_driver",
    "normalize",
    "validate",
    "verify_citations",
    "detect_conflicts",
    "persist_proposals",
)

MODE_STAGES: dict[ExtractionMode, str] = {
    "kpi": "extract_kpi",
    "guidance": "extract_guidance",
    "revenue_driver": "extract_revenue_driver",
}


class Role(StrEnum):
    CLASSIFIER = "classifier"
    FACT_CANDIDATES = "fact_candidates"
    KPI = "kpi"
    GUIDANCE = "guidance"
    DRIVER_MAPPER = "driver_mapper"


@dataclass(frozen=True)
class EvidenceBlock:
    source_span_id: str
    document_version_id: str
    text: str
    text_hash: str
    published_at: datetime | None = None


@dataclass(frozen=True)
class ExtractionRunRequest:
    """Pinned run identity loaded from ``extraction_runs`` / job payload."""

    run_id: str
    org_id: str
    workspace_id: str
    entity_id: str
    modes: tuple[ExtractionMode, ...]
    as_of: datetime
    corpus_version_id: str
    ontology_version: str
    workflow_version: str
    provider: str
    model: str
    policy_id: str
    input_manifest: dict[str, Any]
    input_hash: str
    max_calls: int = 10
    max_input_tokens: int = 100_000
    max_output_tokens: int = 20_000
    max_cost_usd: Decimal = Decimal("2.00")
    max_wall_seconds: int = 600
    issuer_label: str = "Unknown Issuer"


@dataclass
class RunUsage:
    calls_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    cost_usd: Decimal = Decimal("0")


@dataclass
class StageRecord:
    step_name: str
    attempt: int
    status: StepStatus
    input_hash: str
    output_hash: str | None = None
    provider_response_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    error: dict[str, Any] | None = None
    output: Any = None


@dataclass
class ProposalDraft:
    """In-memory proposal before persistence (always needs_review)."""

    kind: ExtractionMode
    metric_id: str
    payload: dict[str, Any]
    raw_payload_hash: str
    definition_hash: str
    comparability_key: dict[str, Any]
    record_confidence: Decimal = Decimal("0")
    field_confidences: dict[str, Any] = field(default_factory=dict)
    validation_summary: dict[str, Any] = field(default_factory=dict)
    review_priority: Literal["normal", "high"] = "high"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    id: str | None = None

    @property
    def state(self) -> ProposalState:
        return "needs_review"


@dataclass
class ConflictDraft:
    conflict_key: str
    reason_codes: list[str]
    member_proposal_ids: list[str]
    id: str | None = None


@dataclass
class WorkflowState:
    """Mutable working state advanced by the stage graph."""

    request: ExtractionRunRequest
    usage: RunUsage = field(default_factory=RunUsage)
    evidence: list[EvidenceBlock] = field(default_factory=list)
    classification: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_proposals: list[dict[str, Any]] = field(default_factory=list)
    normalized: list[dict[str, Any]] = field(default_factory=list)
    validated: list[ProposalDraft] = field(default_factory=list)
    conflicts: list[ConflictDraft] = field(default_factory=list)
    stages: dict[str, StageRecord] = field(default_factory=dict)
    status: RunStatus = "running"
    error: dict[str, Any] | None = None
    abstained: bool = False


def as_uuid(value: str | UUID) -> str:
    return str(value)


__all__ = [
    "ConflictDraft",
    "EvidenceBlock",
    "ExtractionMode",
    "ExtractionRunRequest",
    "MODE_STAGES",
    "NORMALIZER_VERSION",
    "ProposalDraft",
    "ProposalState",
    "Role",
    "RunStatus",
    "RunUsage",
    "STAGE_ORDER",
    "StageRecord",
    "StepStatus",
    "VALIDATOR_VERSION",
    "WORKFLOW_VERSION",
    "WorkflowState",
    "as_uuid",
]
