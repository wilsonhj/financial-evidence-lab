"""Cancellation must reach the workflow from the job handler (#194).

``run_extraction_workflow`` checks ``deps.cancel_check`` at every stage boundary
and again in ``_commit_fence``, but a check nobody wires up is a check that never
fires. These tests pin the seam: ``handle_extraction_run`` accepts
``cancel_check`` and threads it through, and a cancellation observed at a stage
boundary produces a ``run_cancelled`` event, a ``cancelled`` run status, and no
proposals.

Consumer-side wiring — deciding WHEN the predicate returns True, from the
``extraction_runs`` row or a control channel — is separate work; what is pinned
here is that the handler has somewhere for it to plug in and honours it.
"""

from __future__ import annotations

import inspect

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.handler import handle_extraction_run
from fel_workers.extraction.workflow import WorkflowDeps

from .conftest import sample_payload


def test_handler_exposes_a_cancel_check_kwarg_defaulting_to_never() -> None:
    signature = inspect.signature(handle_extraction_run)
    parameter = signature.parameters["cancel_check"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None  # normalised to `lambda: False` in the body
    # The workflow's own default must be "never cancelled", so a caller that
    # supplies nothing gets a run, not an immediate cancellation.
    assert WorkflowDeps(structured_llm=MockStructuredLLMProvider()).cancel_check() is False


def test_uncancelled_run_completes() -> None:
    """Negative control, so the assertions below cannot pass vacuously."""
    state = handle_extraction_run(
        None,
        MockStructuredLLMProvider(),
        sample_payload(),
        use_memory_stores=True,
        cancel_check=lambda: False,
    )
    assert state.status == "waiting_review"
    assert state.validated


def test_cancel_at_the_first_boundary_produces_run_cancelled_and_no_proposals() -> None:
    state = handle_extraction_run(
        None,
        MockStructuredLLMProvider(),
        sample_payload(),
        use_memory_stores=True,
        cancel_check=lambda: True,
    )

    assert state.status == "cancelled"
    assert state.validated == []
    assert (state.error or {}).get("code")


@pytest.mark.parametrize("cancel_after", [1, 3, 5])
def test_cancel_mid_run_stops_at_a_stage_boundary(cancel_after: int) -> None:
    """Cancellation is honoured between stages, never inside one.

    A stage that has already run is committed; the run stops before the next one
    starts. ``cancel_after`` counts boundary checks rather than stages so the
    test does not encode the stage list.
    """
    seen = 0

    def cancel_check() -> bool:
        nonlocal seen
        seen += 1
        return seen > cancel_after

    state = handle_extraction_run(
        None,
        MockStructuredLLMProvider(),
        sample_payload(),
        use_memory_stores=True,
        cancel_check=cancel_check,
    )

    assert state.status == "cancelled"
    assert state.validated == []


def test_cancelled_run_appends_run_cancelled_before_the_status_write() -> None:
    """0004 rejects child inserts once the run row is terminal.

    The event therefore has to be appended BEFORE the status write, or it is lost
    and the guard's error masks the cancellation. The memory stores cannot fail
    that way, but the ordering is what the durable path depends on, so the event
    is asserted here and the ordering itself in ``test_postgres_crash_resume``.
    """
    from fel_workers.extraction.events import MemoryEventStore
    from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
    from fel_workers.extraction.types import WorkflowState
    from fel_workers.extraction.workflow import run_extraction_workflow

    payload = sample_payload()
    events = MemoryEventStore()
    evidence = _evidence_from_payload(payload)
    state = run_extraction_workflow(
        WorkflowState(request=request_from_payload(payload), evidence=list(evidence)),
        WorkflowDeps(
            structured_llm=MockStructuredLLMProvider(),
            events=events,
            evidence_loader=lambda _r: list(evidence),
            cancel_check=lambda: True,
        ),
    )

    assert state.status == "cancelled"
    assert [e.event_type for e in events.events][-1] == "run_cancelled"
