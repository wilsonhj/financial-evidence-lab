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
ReviewPriority = Literal["normal", "high"]

WORKFLOW_VERSION = "extraction-workflow/v1"
NORMALIZER_VERSION = "normalize/v1"
VALIDATOR_VERSION = "validate/v1"

# Internal normalizer metadata key carrying blockers the normalizer detected
# without aborting (a declared scale or sign that contradicts the value). The
# leading underscore means `validate/pipeline.py` strips it before the schema
# check and persist, and `hash_json` never sees it — it is lifted into
# `validation_summary["blockers"]` there instead. Defined here so the normalizer
# and the validator can share the key without importing each other.
NORMALIZER_BLOCKERS_KEY = "_normalizer_blockers"

# Normalizer blockers that say nothing about the row's MAGNITUDE.
#
# `validate/pipeline.py` excludes a row from the accounting identities when the
# normalizer impugned its number — a scale or sign that contradicts the value,
# or an outright rejection, which leaves the payload carried forward
# unnormalized. Those rows cannot be used in arithmetic. The codes below are
# different in kind: they report a malformed *dimension value* or a *missing
# currency*, neither of which makes the row's figure less trustworthy. A row
# carrying only these must keep participating, or a cosmetic typing note
# silently withdraws a deterministic check — cRPO $900m against RPO $500m is
# arithmetically impossible and went unreported because one dimension value
# arrived as `12` rather than `"12"`.
#
# Classification is deliberate and exhaustive: every stable blocker code the
# normalizer can emit is either listed here or gates. A new code that is
# neither is caught by
# `test_every_normalizer_blocker_code_is_deliberately_classified`.
NON_MAGNITUDE_NORMALIZER_BLOCKERS = frozenset(
    {
        "dimensions_non_string",
        "currency_missing_for_monetary",
    }
)

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
    # None means "no calibrator scored this", which is the truth today: #62
    # carries the live scoring work. Decimal("0") was the previous default and
    # was a lie on the column's own scale — 0 reads as "certainly wrong", and a
    # review queue sorted by confidence put every proposal at the bottom
    # (issue #194). Migration 0006 drops the NOT NULL that forced it.
    record_confidence: Decimal | None = None
    field_confidences: dict[str, Any] = field(default_factory=dict)
    validation_summary: dict[str, Any] = field(default_factory=dict)
    # Derived from the validator's findings, never constant — see
    # `validate/pipeline.py::_review_priority_for`.
    review_priority: ReviewPriority = "normal"
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
    "ReviewPriority",
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
