"""Crash-resume must restore pinned evidence verbatim (no silent truncation).

Stage output survives on the step row — ``extraction_run_steps.output``, added by
migration 0006 (ADR-0011) — so these tests exercise the real
serialize -> store -> restore path rather than an in-process cache. Before 0006
the only carrier was the ``step_completed`` event payload, and the redaction that
payload needed for every other key is what truncated a 630-character filing span
to 76 characters while its hash still described the original.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.errors import IntegrityError
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.stages.io import restore_output
from fel_workers.extraction.types import StageRecord, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import sample_payload

# Real filing spans are essentially always longer than the 256-char redaction
# threshold; the shared fixture span is 41 chars, which is why it never tripped.
LONG_SPAN_TEXT = "ARR was $100 million as of June 30, 2026. " * 16


@dataclass
class ReplayCheckpointStore:
    """Fresh-process resume: the step ROW carries the output, nothing else does.

    Mirrors ``PostgresCheckpointStore`` after a crash, whose ``_memory`` cache is
    empty and whose ``load_succeeded`` reads ``extraction_run_steps.output``. The
    stored copy is round-tripped through JSON, because a jsonb column is what the
    real store reads back — an in-process object reference would hide exactly the
    class of defect these tests exist for.

    ``events`` is retained (and unused for hydration) so the suite still runs the
    real event sink alongside the checkpoint: the resume must succeed with the
    events carrying no stage output at all.
    """

    events: MemoryEventStore
    steps: dict[tuple[str, str, str, str], StageRecord] = field(default_factory=dict)

    def load_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        step_name: str,
        input_hash: str,
        workflow_version: str,
    ) -> StageRecord | None:
        del org_id
        record = self.steps.get((run_id, step_name, input_hash, workflow_version))
        if record is None:
            return None
        stored: Any = None if record.output is None else json.loads(json.dumps(record.output))
        return replace(record, output=stored)

    def commit_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord:
        del org_id
        key = (run_id, record.step_name, record.input_hash, workflow_version)
        self.steps.setdefault(key, replace(record))
        return record


def test_long_span_text_survives_the_durable_column_round_trip() -> None:
    """serialize -> jsonb -> restore must not truncate."""
    payload = sample_payload(text=LONG_SPAN_TEXT)
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    serialized = serialize_stage_output(
        [
            {
                "source_span_id": b.source_span_id,
                "document_version_id": b.document_version_id,
                "text": b.text,
                "text_hash": b.text_hash,
                "published_at": b.published_at.isoformat() if b.published_at else None,
            }
            for b in evidence
        ]
    )
    # What `extraction_run_steps.output` hands back on the next connection.
    stored = json.loads(json.dumps(serialized))

    state = WorkflowState(request=request)
    restore_output(state, "assemble_evidence", stored)

    assert state.evidence[0].text == LONG_SPAN_TEXT
    assert state.evidence[0].text_hash == sha256_hex(state.evidence[0].text)


def test_the_event_that_used_to_carry_the_span_text_no_longer_does() -> None:
    """`data-model.md`'s metadata-only guarantee, machine-checked on one event."""
    payload = sample_payload(text=LONG_SPAN_TEXT)
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    events = MemoryEventStore()

    run_extraction_workflow(
        WorkflowState(request=request, evidence=list(evidence)),
        WorkflowDeps(
            structured_llm=MockStructuredLLMProvider(),
            events=events,
            evidence_loader=lambda _r: list(evidence),
        ),
    )

    completed = [e for e in events.events if e.event_type == "step_completed"]
    assert completed, "the run committed no step"
    for event in completed:
        assert "stage_output" not in event.payload
        assert LONG_SPAN_TEXT not in json.dumps(event.payload)


def test_restore_output_fails_closed_on_text_hash_mismatch() -> None:
    """A restored span whose hash no longer describes its text must not load."""
    payload = sample_payload(text=LONG_SPAN_TEXT)
    state = WorkflowState(request=request_from_payload(payload))
    tampered = [
        {
            "source_span_id": payload["evidence"][0]["source_span_id"],
            "document_version_id": payload["evidence"][0]["document_version_id"],
            "text": LONG_SPAN_TEXT[:64],
            "text_hash": sha256_hex(LONG_SPAN_TEXT),
        }
    ]
    with pytest.raises(IntegrityError, match="text_hash"):
        restore_output(state, "assemble_evidence", tampered)


def test_cross_process_resume_keeps_full_evidence_text() -> None:
    """Crash then resume in a fresh process: evidence must come back intact."""
    payload = sample_payload(text=LONG_SPAN_TEXT)
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    events = MemoryEventStore()
    persist = MemoryPersistStore()
    checkpoint = ReplayCheckpointStore(events=events)

    crashed = WorkflowState(request=request, evidence=list(evidence))
    with pytest.raises(RuntimeError, match="injected crash"):
        run_extraction_workflow(
            crashed,
            WorkflowDeps(
                structured_llm=MockStructuredLLMProvider(),
                checkpoint=checkpoint,
                events=events,
                persist=persist,
                evidence_loader=lambda _r: list(evidence),
                crash_after_stages=2,
            ),
        )

    resumed = WorkflowState(request=request)
    final = run_extraction_workflow(
        resumed,
        WorkflowDeps(
            structured_llm=MockStructuredLLMProvider(),
            checkpoint=checkpoint,
            events=events,
            persist=persist,
            evidence_loader=lambda _r: list(evidence),
        ),
    )
    assert final.status == "waiting_review"
    assert [b.text for b in final.evidence] == [LONG_SPAN_TEXT]
