"""A failing stage must leave a diagnosable step row and event behind.

Before this, ``extraction_run_steps`` held no row and no error for the step
that actually broke: ``commit_succeeded`` rejects non-succeeded records and
``step_failed`` was a declared-but-never-emitted event type, so the only signal
was the run-level ``run_failed`` message. That makes step-level diagnosis of a
failed run impossible, and it is indistinguishable from a run that never
reached the stage at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import EvidenceBlock, ExtractionRunRequest, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import FIXTURE_DOC, FIXTURE_ENTITY, FIXTURE_SPAN

# Quoted so the redaction assertion has something to bite on.
SENTINEL = "provider exploded on 'ACME reported ARR of $4.2M'"


class _ExplodingProvider:
    """Fails the first model stage with a non-ExtractionError."""

    def generate_structured(self, request: Any) -> Any:  # noqa: ANN401 - provider protocol
        del request
        raise RuntimeError(SENTINEL)


@dataclass
class _Outcome:
    run_id: str
    events: MemoryEventStore
    checkpoint: MemoryCheckpointStore


def _evidence() -> list[EvidenceBlock]:
    text = "ARR was $100 million as of June 30, 2026."
    return [
        EvidenceBlock(
            source_span_id=FIXTURE_SPAN,
            document_version_id=FIXTURE_DOC,
            text=text,
            text_hash=sha256_hex(text),
            published_at=datetime(2026, 6, 30, tzinfo=UTC),
        )
    ]


@pytest.fixture
def outcome() -> _Outcome:
    request = ExtractionRunRequest(
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
    events, checkpoint = MemoryEventStore(), MemoryCheckpointStore()
    deps = WorkflowDeps(
        structured_llm=_ExplodingProvider(),
        checkpoint=checkpoint,
        events=events,
        persist=MemoryPersistStore(),
        evidence_loader=lambda _r: _evidence(),
    )
    # The run-level handler converts the crash into a terminal failed status
    # rather than propagating, so this returns normally.
    out = run_extraction_workflow(WorkflowState(request=request, evidence=_evidence()), deps)
    assert out.status == "failed", "a crashed stage must land the run as failed"
    return _Outcome(run_id=request.run_id, events=events, checkpoint=checkpoint)


def test_failing_stage_emits_step_failed(outcome: _Outcome) -> None:
    failed = [e for e in outcome.events.events if e.event_type == "step_failed"]
    assert failed, "a failing stage must emit step_failed"
    payload = failed[0].payload
    assert payload["step_name"]
    assert payload["input_hash"]
    assert payload["error"]["code"]


def test_failing_stage_records_a_failed_step(outcome: _Outcome) -> None:
    records = outcome.checkpoint.list_failed(run_id=outcome.run_id)
    assert records, "a failing stage must commit a failed StageRecord"
    assert records[0].status == "failed"
    assert records[0].error is not None
    assert records[0].error["code"]


def test_failed_step_is_never_a_resume_point(outcome: _Outcome) -> None:
    """0004's replay index is partial (WHERE status='succeeded'), so a failed
    attempt must not be handed back by the success-keyed lookup."""
    succeeded = outcome.checkpoint.list_succeeded(run_id=outcome.run_id)
    assert all(r.status == "succeeded" for r in succeeded)


def test_recorded_error_is_redacted(outcome: _Outcome) -> None:
    """The step error lands in a durable column, so it gets the same treatment
    as jobs.error and the event payloads."""
    records = outcome.checkpoint.list_failed(run_id=outcome.run_id)
    error = records[0].error or {}
    assert "ACME reported" not in error.get("message", "")
