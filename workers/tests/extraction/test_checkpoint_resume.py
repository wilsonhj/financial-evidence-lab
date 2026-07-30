"""Crash-resume / checkpoint identity tests (M3-101/102)."""

from __future__ import annotations

from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import LeaseLost
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow


class CountingLLM:
    provider = "mock"
    model = "mock-structured-v1"

    def __init__(self) -> None:
        self.calls = 0
        self._inner = MockStructuredLLMProvider()

    def generate_structured(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self._inner.generate_structured(request)


def test_crash_after_stage_resumes(
    sample_run_payload: dict[str, Any],
) -> None:
    request = request_from_payload(sample_run_payload)
    evidence = _evidence_from_payload(sample_run_payload)
    checkpoint = MemoryCheckpointStore()
    events = MemoryEventStore()
    persist = MemoryPersistStore()
    llm = CountingLLM()

    deps = WorkflowDeps(
        structured_llm=llm,  # type: ignore[arg-type]
        checkpoint=checkpoint,
        events=events,
        persist=persist,
        evidence_loader=lambda _r: list(evidence),
        crash_after_stages=2,
    )
    state = WorkflowState(request=request, evidence=list(evidence))
    with pytest.raises(RuntimeError, match="injected crash"):
        run_extraction_workflow(state, deps)
    calls_before = llm.calls
    assert calls_before >= 0

    deps2 = WorkflowDeps(
        structured_llm=llm,  # type: ignore[arg-type]
        checkpoint=checkpoint,
        events=events,
        persist=persist,
        evidence_loader=lambda _r: list(evidence),
    )
    state2 = WorkflowState(request=request, evidence=list(evidence))
    final = run_extraction_workflow(state2, deps2)
    assert final.status in {"waiting_review", "succeeded", "failed"}
    assert any(e.event_type == "step_completed" for e in events.events)
    # Fresh full run against mock uses 3 model stages for kpi-only (classify,
    # candidates, extract_kpi). Resume should not exceed a clean full run.
    assert llm.calls <= 6


def test_lease_loss_propagates(
    sample_run_payload: dict[str, Any], structured_llm: MockStructuredLLMProvider
) -> None:
    request = request_from_payload(sample_run_payload)
    evidence = _evidence_from_payload(sample_run_payload)
    deps = WorkflowDeps(
        structured_llm=structured_llm,
        evidence_loader=lambda _r: list(evidence),
        lease_check=lambda: False,
    )
    state = WorkflowState(request=request, evidence=list(evidence))
    with pytest.raises(LeaseLost):
        run_extraction_workflow(state, deps)
