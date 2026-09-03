"""Resume-side verification of a restored stage checkpoint (#158), memory path.

`_is_recoverable` used to check exactly one thing — the torn state
(`output_hash` non-null, `output` None). A checkpoint whose durable
`stage_output` had been altered after commit was handed straight back to the
workflow, which recomputed `raw_payload_hash` / `proposal_id_for` from it and
silently forked the run's proposal identity. These tests pin the two halves of
the fix that need no database:

* the write side stamps `stage_output_hash` — a hash of the exact bytes the
  event row holds (post-serialize, post-redact) — into every `step_completed`
  payload, as a sibling of `stage_output`;
* the read side compares a *durably hydrated* record's `output` against that
  hash, rejects a mismatch as unrecoverable (the stage re-runs; the run does
  not fail), and emits a redacted telemetry event that names both hashes and
  never the payload.

The real-Postgres scenarios (mutated durable payload, competing newest event,
legacy rows, the STAGE_ORDER hash-stability pin) live in
`test_postgres_checkpoint_payload_hash.py`.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.events import MemoryEventStore, redact_event_payload
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.hashing import hash_json, sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import StageRecord, WorkflowState
from fel_workers.extraction.workflow import (
    WorkflowDeps,
    _is_recoverable,
    run_extraction_workflow,
)

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_INPUT_HASH = sha256_hex("input")

_HONEST_OUTPUT: dict[str, Any] = {
    "proposals": [{"kind": "kpi", "metric_id": "arr", "raw_value": "$100 million"}]
}
_MUTATED_OUTPUT: dict[str, Any] = {
    "proposals": [{"kind": "kpi", "metric_id": "arr", "raw_value": "$900 million"}]
}


def _run_in_memory(sample_run_payload: dict[str, Any]) -> tuple[WorkflowState, MemoryEventStore]:
    request = request_from_payload(sample_run_payload)
    evidence = _evidence_from_payload(sample_run_payload)
    events = MemoryEventStore()
    deps = WorkflowDeps(
        structured_llm=MockStructuredLLMProvider(),
        events=events,
        persist=MemoryPersistStore(),
        evidence_loader=lambda _r: list(evidence),
    )
    state = run_extraction_workflow(WorkflowState(request=request, evidence=list(evidence)), deps)
    assert state.status == "waiting_review"
    return state, events


def _hydrated(output: Any, *, durable_output_hash: str | None) -> StageRecord:
    """A record shaped the way `PostgresCheckpointStore.load_succeeded` builds one."""
    return StageRecord(
        step_name="extract_kpi",
        attempt=1,
        status="succeeded",
        input_hash=_INPUT_HASH,
        output_hash=hash_json(_HONEST_OUTPUT),
        output=output,
        durable_output_hash=durable_output_hash,
    )


# ---------------------------------------------------------------------------
# Write side — the hash rides the event, beside the payload it describes.
# ---------------------------------------------------------------------------


def test_step_completed_payload_carries_the_hash_of_its_own_durable_stage_output(
    sample_run_payload: dict[str, Any],
) -> None:
    """`stage_output_hash` must describe the bytes the row holds, not the live object.

    `output_hash` is `hash_json` over the stage's live return value, computed one
    line before `serialize_stage_output` produces what is actually stored; the
    two are different functions of the same value (a dataclass hashes as its
    `repr`, a tuple stringifies). The stamp therefore has to be taken over the
    serialized, redacted subtree — exactly what `_load_stage_output` reads back.
    """
    _, events = _run_in_memory(sample_run_payload)

    completed = [e.payload for e in events.events if e.event_type == "step_completed"]
    assert completed, "the run committed no step_completed events"
    for payload in completed:
        stored = redact_event_payload(payload, event_type="step_completed")
        assert payload.get("stage_output_hash") == hash_json(stored["stage_output"]), payload[
            "step_name"
        ]


def test_in_process_stage_records_carry_no_durable_hash(
    sample_run_payload: dict[str, Any],
) -> None:
    """Only a record hydrated from the durable event may carry the field.

    `PostgresCheckpointStore.load_succeeded` answers from its in-process cache
    first, where `output` is the LIVE object. Comparing that to a hash of the
    serialized+redacted form would false-positive on every same-process resume,
    so the live record must never be stamped.
    """
    state, _ = _run_in_memory(sample_run_payload)

    for step_name, record in state.stages.items():
        assert record.durable_output_hash is None, step_name


# ---------------------------------------------------------------------------
# Read side — `_is_recoverable` verifies a hydrated record before resume.
# ---------------------------------------------------------------------------


def test_mismatched_durable_payload_is_unrecoverable(caplog: pytest.LogCaptureFixture) -> None:
    """A mutated `stage_output` must send the stage back through `_run_stage`.

    Returning False is what makes the stage RE-RUN. Raising `IntegrityError`
    here would take the `StepFailed` branch and land the run terminal `failed`,
    which 0004 makes permanent — a corrupted checkpoint would kill the run.
    """
    record = _hydrated(_MUTATED_OUTPUT, durable_output_hash=hash_json(_HONEST_OUTPUT))

    with caplog.at_level(logging.INFO, logger="fel_workers.extraction.telemetry"):
        assert _is_recoverable(record, run_id=_RUN_ID) is False


def test_matching_durable_payload_is_recoverable() -> None:
    record = _hydrated(_HONEST_OUTPUT, durable_output_hash=hash_json(_HONEST_OUTPUT))

    assert _is_recoverable(record, run_id=_RUN_ID) is True


def test_record_without_a_durable_hash_resumes_exactly_as_before() -> None:
    """Rows written before the field existed carry no hash: no check, no change."""
    record = _hydrated(_MUTATED_OUTPUT, durable_output_hash=None)

    assert _is_recoverable(record, run_id=_RUN_ID) is True


def test_mismatch_emits_redacted_telemetry_naming_both_hashes_and_never_the_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    expected = hash_json(_HONEST_OUTPUT)
    actual = hash_json(_MUTATED_OUTPUT)
    record = _hydrated(_MUTATED_OUTPUT, durable_output_hash=expected)

    with caplog.at_level(logging.INFO, logger="fel_workers.extraction.telemetry"):
        _is_recoverable(record, run_id=_RUN_ID)

    lines = [
        r.getMessage()
        for r in caplog.records
        if "stage_checkpoint_payload_mismatch" in r.getMessage()
    ]
    assert len(lines) == 1, caplog.text
    line = lines[0]
    for needle in (_RUN_ID, "extract_kpi", _INPUT_HASH, expected, actual):
        assert needle in line, needle
    # The payload itself — filing-derived text — must never reach a log line.
    assert "$900 million" not in line
    assert "$100 million" not in line
    assert "proposals" not in line
