"""Stage-level audit + fencing regressions (P1-2a / P1-8.1 / P1-4.3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import LeaseLost
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import (
    EvidenceBlock,
    ExtractionRunRequest,
    WorkflowState,
)
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import FIXTURE_DOC, FIXTURE_ENTITY, FIXTURE_SPAN

_EVIDENCE_TEXT = "ARR was $100 million as of June 30, 2026."


def _request() -> ExtractionRunRequest:
    return ExtractionRunRequest(
        run_id=str(uuid4()),
        org_id=str(uuid4()),
        workspace_id=str(uuid4()),
        entity_id=FIXTURE_ENTITY,
        modes=("kpi",),
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        corpus_version_id=str(uuid4()),
        ontology_version="saas-metrics/v1",
        workflow_version="extraction-workflow/v1",
        provider="mock",
        model="mock-structured-v1",
        policy_id=str(uuid4()),
        input_manifest={"source_span_ids": [FIXTURE_SPAN]},
        input_hash=sha256_hex("manifest"),
        issuer_label="Example SaaS",
    )


def _evidence() -> list[EvidenceBlock]:
    return [
        EvidenceBlock(
            source_span_id=FIXTURE_SPAN,
            document_version_id=FIXTURE_DOC,
            text=_EVIDENCE_TEXT,
            text_hash=sha256_hex(_EVIDENCE_TEXT),
            published_at=datetime(2026, 6, 30, tzinfo=UTC),
        )
    ]


def _unnormalizable_kpi() -> dict[str, Any]:
    """Schema-valid per ``validate_payload_item`` but rejected by the normalizer.

    ``period.type == "instant"`` without ``instant`` raises
    ``ValueError("instant period requires instant date")``, which is exactly the
    payload the silent ``except ValueError: continue`` used to swallow.
    """
    return {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": FIXTURE_ENTITY,
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "value": "100",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "instant"},
        "dimensions": {},
        "definition": "Annual recurring revenue",
        "qualifiers": {
            "currency": "USD",
            "construction": "reported_arr",
            "scope": "consolidated",
        },
        "reported_or_derived": "reported",
        "evidence": [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "role": "supports",
            }
        ],
    }


class _KpiOverrideProvider:
    """Mock provider that swaps the KPI envelope for a scripted one."""

    provider = "mock"
    model = "mock-structured-v1"

    def __init__(self, proposals: list[dict[str, Any]]) -> None:
        self._mock = MockStructuredLLMProvider()
        self._proposals = proposals

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = self._mock.generate_structured(request)
        if request.schema_name != "kpi":
            return result
        return replace(result, parsed={"proposals": self._proposals, "notes": None})


def _run(provider: Any, **dep_overrides: Any) -> WorkflowState:
    state = WorkflowState(request=_request(), evidence=_evidence())
    deps = WorkflowDeps(
        structured_llm=provider,
        persist=MemoryPersistStore(),
        evidence_loader=lambda _r: _evidence(),
        **dep_overrides,
    )
    return run_extraction_workflow(state, deps)


# --------------------------------------------------------------------------
# P1-2a — an unnormalizable proposal must never vanish silently
# --------------------------------------------------------------------------


def test_unnormalizable_proposal_is_counted_in_the_stage_output() -> None:
    out = _run(_KpiOverrideProvider([_unnormalizable_kpi()]))

    normalize_output = out.stages["normalize"].output
    assert isinstance(normalize_output, dict), "normalize output must carry counts"
    assert normalize_output["blocked_count"] == 1
    assert normalize_output["normalized_count"] == 1


def test_unnormalizable_proposal_reaches_review_with_its_reason() -> None:
    out = _run(_KpiOverrideProvider([_unnormalizable_kpi()]))

    # Total loss must not masquerade as a legitimate abstention.
    assert out.status == "waiting_review"
    assert out.abstained is False
    assert len(out.validated) == 1
    blockers = out.validated[0].validation_summary["blockers"]
    assert any("instant period requires instant date" in b for b in blockers), blockers


def test_normalizable_proposal_reports_zero_blocked() -> None:
    out = _run(MockStructuredLLMProvider())

    normalize_output = out.stages["normalize"].output
    assert normalize_output["blocked_count"] == 0
    assert normalize_output["normalized_count"] == 1
    assert out.status == "waiting_review"


def test_run_succeeded_abstention_event_reports_the_blocked_count() -> None:
    """A genuine abstention is distinguishable from loss at the run level."""
    events = MemoryEventStore()
    state = WorkflowState(request=_request(), evidence=_evidence())
    deps = WorkflowDeps(
        structured_llm=_KpiOverrideProvider([]),
        persist=MemoryPersistStore(),
        events=events,
        evidence_loader=lambda _r: _evidence(),
    )
    out = run_extraction_workflow(state, deps)

    assert out.status == "succeeded"
    assert out.abstained is True
    succeeded = [e for e in events.events if e.event_type == "run_succeeded"]
    assert succeeded[0].payload == {"abstained": True, "normalize_blocked_count": 0}


@pytest.mark.parametrize("proposals", [[], [_unnormalizable_kpi()]])
def test_normalize_stage_output_always_carries_both_counts(
    proposals: list[dict[str, Any]],
) -> None:
    out = _run(_KpiOverrideProvider(proposals))
    normalize_output = out.stages["normalize"].output
    assert set(normalize_output) == {"normalized", "normalized_count", "blocked_count"}


# --------------------------------------------------------------------------
# P1-8.1 — the per-step audit trail must reach the StageRecord
# --------------------------------------------------------------------------


class _RecordingProvider:
    """Mock provider that remembers what it answered, per schema."""

    provider = "mock"
    model = "mock-structured-v1"

    def __init__(self) -> None:
        self._mock = MockStructuredLLMProvider()
        self.response_ids: list[str] = []

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = self._mock.generate_structured(request)
        self.response_ids.append(result.response_id)
        return result


class _RepairOnceProvider(_RecordingProvider):
    """Returns one schema-invalid KPI envelope, then answers normally."""

    def __init__(self) -> None:
        super().__init__()
        self._sent_junk = False

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = super().generate_structured(request)
        if request.schema_name == "kpi" and not self._sent_junk:
            self._sent_junk = True
            return replace(result, parsed={"proposals": [{"kind": "kpi"}], "notes": None})
        return result


def test_model_stage_records_provider_response_and_tokens() -> None:
    provider = _RecordingProvider()
    out = _run(provider)

    for step_name in ("classify", "collect_candidates", "extract_kpi"):
        record = out.stages[step_name]
        assert record.provider_response_id in provider.response_ids, step_name
        assert record.input_tokens > 0, step_name
        assert record.output_tokens > 0, step_name
        assert record.attempt == 1, step_name


def test_non_model_stage_keeps_empty_provenance() -> None:
    out = _run(_RecordingProvider())

    for step_name in ("validate_request", "normalize", "persist_proposals"):
        record = out.stages[step_name]
        assert record.provider_response_id is None, step_name
        assert record.input_tokens == 0, step_name
        assert record.output_tokens == 0, step_name
        assert record.attempt == 1, step_name


def test_repaired_stage_records_attempt_two_and_the_accepted_response() -> None:
    provider = _RepairOnceProvider()
    out = _run(provider)

    record = out.stages["extract_kpi"]
    assert record.attempt == 2, "a repaired step must not report attempt 1"
    # The accepted answer is the last one the provider gave, not the rejected one.
    assert record.provider_response_id == provider.response_ids[-1]


def test_per_step_tokens_reconcile_with_the_run_total() -> None:
    out = _run(_RepairOnceProvider())

    assert sum(r.input_tokens for r in out.stages.values()) == out.usage.input_tokens_used
    assert sum(r.output_tokens for r in out.stages.values()) == out.usage.output_tokens_used
    assert sum((r.cost_usd for r in out.stages.values()), Decimal("0")) == out.usage.cost_usd


def test_step_completed_event_carries_the_hashes_that_have_no_column() -> None:
    """instructions_hash / attempt_request_hashes have no 0004 column."""
    events = MemoryEventStore()
    state = WorkflowState(request=_request(), evidence=_evidence())
    deps = WorkflowDeps(
        structured_llm=_RepairOnceProvider(),
        persist=MemoryPersistStore(),
        events=events,
        evidence_loader=lambda _r: _evidence(),
    )
    run_extraction_workflow(state, deps)

    completed = {
        e.payload["step_name"]: e.payload for e in events.events if e.event_type == "step_completed"
    }
    model_step = completed["extract_kpi"]["model_step"]
    assert model_step["attempts"] == 2
    assert model_step["instructions_hash"].startswith("sha256:")
    assert len(model_step["attempt_request_hashes"]) == 2
    assert len(model_step["provider_response_ids"]) == 2
    # Non-model stages carry no such block.
    assert "model_step" not in completed["normalize"]


# --------------------------------------------------------------------------
# P1-4.3 — nothing durable may be written after the lease or run is gone
# --------------------------------------------------------------------------


class _LeaseDroppingProvider(_RecordingProvider):
    """Drops the queue lease mid-``classify``, as a heartbeat failure would."""

    def __init__(self) -> None:
        super().__init__()
        self.lease_alive = True

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = super().generate_structured(request)
        if request.schema_name == "classifier":
            self.lease_alive = False
        return result


class _CancellingProvider(_RecordingProvider):
    """Run is cancelled while ``classify`` is in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = super().generate_structured(request)
        if request.schema_name == "classifier":
            self.cancelled = True
        return result


def test_lease_lost_during_dispatch_blocks_the_durable_commit() -> None:
    """A worker that no longer owns the job must not commit the stage it just ran."""
    provider = _LeaseDroppingProvider()
    checkpoint = MemoryCheckpointStore()
    events = MemoryEventStore()
    state = WorkflowState(request=_request(), evidence=_evidence())
    deps = WorkflowDeps(
        structured_llm=provider,
        checkpoint=checkpoint,
        events=events,
        persist=MemoryPersistStore(),
        evidence_loader=lambda _r: _evidence(),
        lease_check=lambda: provider.lease_alive,
    )

    with pytest.raises(LeaseLost):
        run_extraction_workflow(state, deps)

    committed = {r.step_name for r in checkpoint.list_succeeded(run_id=state.request.run_id)}
    assert committed == {"validate_request", "assemble_evidence"}
    # `extraction_run_events` has no uniqueness constraint and `_load_stage_output`
    # reads the newest row, so a zombie's `step_completed` would win on resume.
    completed = {e.payload["step_name"] for e in events.events if e.event_type == "step_completed"}
    assert "classify" not in completed


def test_cancellation_during_dispatch_blocks_the_durable_commit() -> None:
    provider = _CancellingProvider()
    checkpoint = MemoryCheckpointStore()
    state = WorkflowState(request=_request(), evidence=_evidence())
    deps = WorkflowDeps(
        structured_llm=provider,
        checkpoint=checkpoint,
        persist=MemoryPersistStore(),
        evidence_loader=lambda _r: _evidence(),
        cancel_check=lambda: provider.cancelled,
    )

    out = run_extraction_workflow(state, deps)

    assert out.status == "cancelled"
    committed = {r.step_name for r in checkpoint.list_succeeded(run_id=state.request.run_id)}
    assert committed == {"validate_request", "assemble_evidence"}
