"""A checkpoint must prove it is the output it claims (#158, ADR-0011).

``extraction_run_steps.output`` is durable, mutable within an open run, and — on
resume — trusted enough to skip a stage that has already been paid for. The only
thing that makes trusting it safe is ``output_hash``: ``hash_json`` over exactly
the value stored in the column, recomputed on the way back in.

Without that recomputation a corrupted or tampered ``output`` is laundered into
proposal identity. ``_restore_output`` re-checks ``text_hash`` for
``assemble_evidence``'s span text and nothing else, and the model-derived
subtrees — ``classification``, ``candidates``, ``raw_proposals``,
``normalized`` — have no content address at all. A resumed run would recompute
``raw_payload_hash`` and ``proposal_id_for`` from whatever it read back and emit
proposals that are internally consistent and describe something the extractor
never produced.

The answer is to re-run the stage, which is always available: stages are
idempotent by construction, keyed on ``input_hash``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.types import StageRecord, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import sample_payload

_TAMPERED_STEP = "classify"


class _CountingLLM:
    """Counts model calls, so a stage that was skipped is distinguishable."""

    def __init__(self) -> None:
        self._inner = MockStructuredLLMProvider()
        self.provider = self._inner.provider
        self.model = self._inner.model
        self.calls = 0

    def generate_structured(self, request: Any) -> Any:
        self.calls += 1
        return self._inner.generate_structured(request)


@dataclass
class _RowCheckpointStore:
    """A checkpoint whose rows can be tampered with, like the real column can.

    ``extraction_run_steps.output`` is UPDATE-able within an open run (0004's
    guard pins identity columns, not output), and a database is not a trusted
    memory space: backups, replicas, operators and bugs all reach it. This double
    models that directly — ``tamper`` rewrites a stored row's ``output`` while
    leaving ``output_hash`` describing the original, which is exactly the state
    the hash check exists to detect.
    """

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
        return None if record is None else replace(record)

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

    def tamper(self, step_name: str, mutate: Any) -> StageRecord:
        for key, record in self.steps.items():
            if key[1] == step_name:
                self.steps[key] = replace(record, output=mutate(record.output))
                return self.steps[key]
        raise AssertionError(f"no committed step {step_name!r} to tamper with")

    def drop_output(self, step_name: str) -> StageRecord:
        """The legacy torn row: output_hash set, output NULL, unrepairable."""
        return self.tamper(step_name, lambda _out: None)


def _run(deps_kwargs: dict[str, Any], payload: dict[str, Any]) -> WorkflowState:
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    state = WorkflowState(request=request, evidence=list(evidence))
    return run_extraction_workflow(
        state,
        WorkflowDeps(evidence_loader=lambda _r: list(evidence), **deps_kwargs),
    )


def test_committed_checkpoint_hash_describes_the_stored_output() -> None:
    """The invariant every other test here depends on."""
    payload = sample_payload()
    checkpoint = _RowCheckpointStore()
    _run(
        {"structured_llm": MockStructuredLLMProvider(), "checkpoint": checkpoint},
        payload,
    )

    assert checkpoint.steps, "the run committed no step"
    for record in checkpoint.steps.values():
        if record.output is None:
            assert record.output_hash is None
            continue
        assert record.output_hash == hash_json(record.output)


def test_tampered_output_forces_the_stage_to_re_execute() -> None:
    """A stored output that no longer hashes to its output_hash is not a checkpoint.

    The tamper is realistic rather than cosmetic: it rewrites the classifier's
    verdict, which steers every downstream stage. If the resume trusted it, the
    run would extract under a classification the extractor never produced, and
    the proposals would carry hashes computed over the substituted payload.
    """
    payload = sample_payload()
    checkpoint = _RowCheckpointStore()
    events = MemoryEventStore()
    first = _CountingLLM()
    _run(
        {"structured_llm": first, "checkpoint": checkpoint, "events": events},
        payload,
    )
    assert first.calls >= 1

    tampered = checkpoint.tamper(
        _TAMPERED_STEP, lambda out: {**out, "document_type": "press_release"}
    )
    assert tampered.output_hash != hash_json(tampered.output)

    resumed_events = MemoryEventStore()
    second = _CountingLLM()
    final = _run(
        {"structured_llm": second, "checkpoint": checkpoint, "events": resumed_events},
        payload,
    )

    assert second.calls >= 1, "the tampered stage was trusted instead of re-run"
    assert final.status == "waiting_review"
    # The rejection is reported, and reported as a rejection rather than as a
    # generic step failure: the event vocabulary is frozen (0004's event_type
    # CHECK has no `checkpoint_rejected` member), so the reason rides in the
    # payload.
    rejections = [
        e
        for e in resumed_events.events
        if e.event_type == "step_failed"
        and (e.payload.get("error") or {}).get("code") == "checkpoint_rejected"
    ]
    assert rejections, "a rejected checkpoint was not reported at all"
    assert rejections[0].payload["reason"] == "checkpoint_hash_mismatch"
    assert rejections[0].payload["step_name"] == _TAMPERED_STEP
    assert rejections[0].payload["action"] == "stage_re_executed"


def test_untampered_checkpoint_is_still_trusted() -> None:
    """The negative control: hash verification must not defeat resume itself."""
    payload = sample_payload()
    checkpoint = _RowCheckpointStore()
    first = _CountingLLM()
    _run({"structured_llm": first, "checkpoint": checkpoint}, payload)

    second = _CountingLLM()
    final = _run({"structured_llm": second, "checkpoint": checkpoint}, payload)

    assert second.calls == 0, "an intact checkpoint was re-executed"
    assert final.status == "waiting_review"
    assert final.validated


def test_legacy_row_with_no_output_is_rejected_not_skipped() -> None:
    """Pre-0006 rows are unrepairable, so the resume-side guard is permanent.

    0004 forbids UPDATE on a terminal run and DELETE outright, so a step row
    written before migration 0006 keeps `output_hash` set and `output` NULL
    forever. Treating it as a completed stage is the silent-abstention defect:
    the stage is skipped with zero model calls and the run reports success with
    no proposals.
    """
    payload = sample_payload()
    checkpoint = _RowCheckpointStore()
    _run({"structured_llm": MockStructuredLLMProvider(), "checkpoint": checkpoint}, payload)
    torn = checkpoint.drop_output(_TAMPERED_STEP)
    assert torn.output is None and torn.output_hash is not None

    events = MemoryEventStore()
    second = _CountingLLM()
    final = _run(
        {"structured_llm": second, "checkpoint": checkpoint, "events": events},
        payload,
    )

    assert second.calls >= 1
    assert not final.abstained
    assert final.validated
    reasons = {
        e.payload.get("reason")
        for e in events.events
        if e.event_type == "step_failed"
        and (e.payload.get("error") or {}).get("code") == "checkpoint_rejected"
    }
    assert reasons == {"checkpoint_output_missing"}


@pytest.mark.parametrize("step_name", ["assemble_evidence", "normalize"])
def test_hash_verification_covers_every_stage_not_just_evidence(step_name: str) -> None:
    """`_restore_output`'s text_hash check covers span text only.

    `normalize`'s output is model-derived and has no other content address, so
    without `output_hash` verification nothing at all would notice a substituted
    payload there. Both stages must behave identically.
    """
    payload = sample_payload()
    checkpoint = _RowCheckpointStore()
    _run({"structured_llm": MockStructuredLLMProvider(), "checkpoint": checkpoint}, payload)

    def _mutate(out: Any) -> Any:
        if isinstance(out, dict):
            return {**out, "injected": "not in the original"}
        return [*out, {"injected": "not in the original"}]

    checkpoint.tamper(step_name, _mutate)

    events = MemoryEventStore()
    second = _CountingLLM()
    _run({"structured_llm": second, "checkpoint": checkpoint, "events": events}, payload)

    rejected = [
        e.payload["step_name"]
        for e in events.events
        if e.event_type == "step_failed"
        and (e.payload.get("error") or {}).get("code") == "checkpoint_rejected"
    ]
    assert step_name in rejected
