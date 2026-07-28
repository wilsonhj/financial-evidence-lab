"""Unexpected (non-typed) failures must still land the run row (M3-WF-010).

A run stuck in ``running`` after a crash is indistinguishable from an in-flight
one, which is exactly the property this package claims to provide.
"""

from __future__ import annotations

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.errors import LeaseLost
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import sample_payload


def _deps(**overrides: object) -> WorkflowDeps:
    payload = sample_payload(modes=["kpi"])
    evidence = _evidence_from_payload(payload)
    base: dict[str, object] = {
        "structured_llm": MockStructuredLLMProvider(),
        "events": MemoryEventStore(),
        "persist": MemoryPersistStore(),
        "evidence_loader": lambda _r: list(evidence),
    }
    base.update(overrides)
    return WorkflowDeps(**base)  # type: ignore[arg-type]


def test_unexpected_exception_fails_the_run_row_and_reraises() -> None:
    """A RuntimeError escaping the stage graph must not leave the run running."""
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload(payload)
    evidence = _evidence_from_payload(payload)
    events = MemoryEventStore()
    persist = MemoryPersistStore()
    deps = WorkflowDeps(
        structured_llm=MockStructuredLLMProvider(),
        events=events,
        persist=persist,
        evidence_loader=lambda _r: list(evidence),
        crash_after_stages=1,
    )
    state = WorkflowState(request=request, evidence=list(evidence))

    # The traceback must still surface so the job fails and the queue retries.
    with pytest.raises(RuntimeError, match="injected crash"):
        run_extraction_workflow(state, deps)

    assert state.status == "failed"
    assert persist.run_status[request.run_id] == "failed"
    failures = [e for e in events.events if e.event_type == "run_failed"]
    assert failures and failures[-1].payload["code"] == "internal_error"


def test_lease_loss_still_writes_nothing() -> None:
    """LeaseLost keeps its distinct handling: no status write, no run_failed."""
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload(payload)
    events = MemoryEventStore()
    persist = MemoryPersistStore()
    deps = _deps(events=events, persist=persist, lease_check=lambda: False)
    state = WorkflowState(request=request, evidence=_evidence_from_payload(payload))

    with pytest.raises(LeaseLost):
        run_extraction_workflow(state, deps)

    assert request.run_id not in persist.run_status
    assert not [e for e in events.events if e.event_type == "run_failed"]


def test_cancellation_still_marks_cancelled() -> None:
    """Cancelled keeps its distinct handling and is not folded into failed."""
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload(payload)
    events = MemoryEventStore()
    persist = MemoryPersistStore()
    deps = _deps(events=events, persist=persist, cancel_check=lambda: True)
    state = WorkflowState(request=request, evidence=_evidence_from_payload(payload))

    out = run_extraction_workflow(state, deps)

    assert out.status == "cancelled"
    assert persist.run_status[request.run_id] == "cancelled"
    assert [e for e in events.events if e.event_type == "run_cancelled"]
