"""Crash-resume must restore pinned evidence verbatim (no silent truncation).

Stage output survives only in the ``step_completed`` event payload (frozen 0004
has no ``steps.output`` column), so these tests exercise the real
serialize -> redact -> restore path rather than an in-process cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.errors import IntegrityError
from fel_workers.extraction.events import MemoryEventStore, redact_event_payload
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.types import StageRecord, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, _restore_output, run_extraction_workflow

from .conftest import sample_payload

# Real filing spans are essentially always longer than the 256-char redaction
# threshold; the shared fixture span is 41 chars, which is why it never tripped.
LONG_SPAN_TEXT = "ARR was $100 million as of June 30, 2026. " * 16


@dataclass
class ReplayCheckpointStore:
    """Fresh-process resume: step rows keep no output; events rehydrate it.

    Mirrors ``PostgresCheckpointStore`` after a crash, whose ``_memory`` cache is
    empty and whose ``_load_stage_output`` reads the persisted event payload.
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
        return replace(record, output=self._stage_output(step_name, input_hash))

    def _stage_output(self, step_name: str, input_hash: str) -> Any:
        for event in reversed(self.events.events):
            payload = event.payload
            if (
                event.event_type == "step_completed"
                and payload.get("step_name") == step_name
                and payload.get("input_hash") == input_hash
            ):
                return payload.get("stage_output")
        return None

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
        self.steps.setdefault(key, replace(record, output=None))
        return record


def test_long_span_text_survives_event_round_trip() -> None:
    """serialize -> redact (the persisted row) -> restore must not truncate."""
    payload = sample_payload(text=LONG_SPAN_TEXT)
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    stored = redact_event_payload(
        {
            "step_name": "assemble_evidence",
            "input_hash": sha256_hex("assemble_evidence"),
            "stage_output": serialize_stage_output(
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
            ),
        },
        event_type="step_completed",
    )

    state = WorkflowState(request=request)
    _restore_output(state, "assemble_evidence", stored["stage_output"])

    assert state.evidence[0].text == LONG_SPAN_TEXT
    assert state.evidence[0].text_hash == sha256_hex(state.evidence[0].text)


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
        _restore_output(state, "assemble_evidence", tampered)


class _ProcessDeath(BaseException):
    """SIGKILL/OOM: bypasses every handler, so the run row stays ``running``.

    A handled crash lands the row ``failed``, and terminal runs are final
    (#146): the consumer never re-dispatches that job and both persist stores
    refuse to reopen the row. Resume exists only for this shape of death.
    """


class _DyingLLM:
    """Dies on the first model call — after assemble_evidence has committed."""

    provider = "mock"
    model = "mock-structured-v1"

    def generate_structured(self, request: Any) -> Any:
        raise _ProcessDeath("simulated process death")


def test_cross_process_resume_keeps_full_evidence_text() -> None:
    """Crash then resume in a fresh process: evidence must come back intact."""
    payload = sample_payload(text=LONG_SPAN_TEXT)
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    events = MemoryEventStore()
    persist = MemoryPersistStore()
    checkpoint = ReplayCheckpointStore(events=events)

    crashed = WorkflowState(request=request, evidence=list(evidence))
    with pytest.raises(_ProcessDeath):
        run_extraction_workflow(
            crashed,
            WorkflowDeps(
                structured_llm=_DyingLLM(),
                checkpoint=checkpoint,
                events=events,
                persist=persist,
                evidence_loader=lambda _r: list(evidence),
            ),
        )
    # No handler ran: no terminal status was written, so the run is resumable.
    assert persist.run_status.get(request.run_id) is None

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
