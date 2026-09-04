"""Run budget must survive a requeue (M3-WF-005/006).

A run's caps bound the *run*, not one queue attempt: with ``max_attempts=5`` a
per-attempt reset lets a run configured for $2.00 spend $10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import BudgetExceeded
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.handler import _evidence_from_payload, request_from_payload
from fel_workers.extraction.persist import MemoryPersistStore, RunAlreadyTerminal, UsageSnapshot
from fel_workers.extraction.types import WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import sample_payload


class _ProcessDeath(BaseException):
    """SIGKILL/OOM: no handler runs, so the run row stays ``running``.

    That is the only shape of crash a requeue can resume. A handled failure
    lands the row ``failed`` — terminal — and terminal runs are final (#146):
    the consumer dead-letters the job instead of re-dispatching it.
    """


class CountingLLM:
    provider = "mock"
    model = "mock-structured-v1"

    def __init__(self, *, die_after: int | None = None) -> None:
        self.calls = 0
        self.die_after = die_after
        self._inner = MockStructuredLLMProvider()

    def generate_structured(self, request: Any) -> Any:
        if self.die_after is not None and self.calls >= self.die_after:
            raise _ProcessDeath("simulated process death")
        self.calls += 1
        return self._inner.generate_structured(request)


@dataclass
class OrderedPersistStore(MemoryPersistStore):
    """Records the order of run-row writes."""

    order: list[str] = field(default_factory=list)

    def record_usage(self, *, run_id: str, org_id: str, usage: UsageSnapshot) -> None:
        self.order.append("record_usage")
        super().record_usage(run_id=run_id, org_id=org_id, usage=usage)

    def set_run_status(
        self,
        *,
        run_id: str,
        org_id: str,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        self.order.append(f"set_run_status:{status}")
        super().set_run_status(run_id=run_id, org_id=org_id, status=status, error=error)


def test_wall_clock_elapsed_carries_across_attempts() -> None:
    """Seconds burned by earlier attempts count against the run's wall cap."""
    budget = RunBudget(max_wall_seconds=10, wall_seconds_used=30.0)
    assert budget.elapsed_seconds() >= 30.0
    with pytest.raises(BudgetExceeded, match="wall clock"):
        budget.precheck(reserve_output_tokens=1)


def test_usage_is_persisted_when_the_budget_trips() -> None:
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload({**payload, "max_calls": 2})
    evidence = _evidence_from_payload(payload)
    persist = MemoryPersistStore()
    events = MemoryEventStore()
    llm = CountingLLM()

    state = WorkflowState(request=request, evidence=list(evidence))
    out = run_extraction_workflow(
        state,
        WorkflowDeps(
            structured_llm=llm,  # type: ignore[arg-type]
            checkpoint=MemoryCheckpointStore(),
            events=events,
            persist=persist,
            evidence_loader=lambda _r: list(evidence),
        ),
    )

    assert out.status == "failed"
    assert (out.error or {})["code"] == "budget_exceeded"
    assert llm.calls == 2
    carried = persist.load_usage(run_id=request.run_id, org_id=request.org_id)
    assert carried.calls_used == 2
    assert carried.input_tokens_used > 0
    assert carried.wall_seconds_used > 0
    assert any(e.event_type == "budget_updated" for e in events.events)


@pytest.mark.parametrize("max_calls", [2, 10])
def test_usage_lands_before_the_terminal_status_write(max_calls: int) -> None:
    """Frozen 0004 refuses to mutate a run row that already reached a terminal
    status, so the usage flush must precede the failed/succeeded write."""
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload({**payload, "max_calls": max_calls})
    evidence = _evidence_from_payload(payload)
    persist = OrderedPersistStore()

    run_extraction_workflow(
        WorkflowState(request=request, evidence=list(evidence)),
        WorkflowDeps(
            structured_llm=MockStructuredLLMProvider(),
            checkpoint=MemoryCheckpointStore(),
            events=MemoryEventStore(),
            persist=persist,
            evidence_loader=lambda _r: list(evidence),
        ),
    )

    status_writes = [i for i, call in enumerate(persist.order) if call.startswith("set_run_status")]
    assert status_writes, persist.order
    assert persist.order.index("record_usage") < status_writes[0]
    assert "record_usage" not in persist.order[status_writes[0] :]


def test_requeued_attempt_does_not_reset_the_budget() -> None:
    """Attempt two resumes from the spent budget instead of starting at zero.

    The first attempt dies the way a resumable run dies: process death after
    real spend, run row still ``running``. With ``max_calls=2`` and one call
    already flushed, the resumed attempt gets exactly one more call before the
    cap trips; a reset budget would have let it make a third.
    """
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload({**payload, "max_calls": 2})
    evidence = _evidence_from_payload(payload)
    persist = MemoryPersistStore()
    events = MemoryEventStore()
    checkpoint = MemoryCheckpointStore()
    llm = CountingLLM(die_after=1)

    def attempt() -> WorkflowState:
        return run_extraction_workflow(
            WorkflowState(request=request, evidence=list(evidence)),
            WorkflowDeps(
                structured_llm=llm,  # type: ignore[arg-type]
                checkpoint=checkpoint,
                events=events,
                persist=persist,
                evidence_loader=lambda _r: list(evidence),
            ),
        )

    with pytest.raises(_ProcessDeath):
        attempt()
    assert llm.calls == 1
    # No handler ran, so no terminal status was written (mark_running is the
    # queue handler's; a direct workflow call never writes a non-terminal one).
    assert persist.run_status.get(request.run_id) is None, "process death must stay resumable"
    carried = persist.load_usage(run_id=request.run_id, org_id=request.org_id)
    assert carried.calls_used == 1, "spend was not flushed before the process died"

    llm.die_after = None
    second = attempt()
    assert second.status == "failed"
    assert (second.error or {})["code"] == "budget_exceeded"
    assert llm.calls == 2, "requeue re-spent the exhausted call budget"


def test_second_attempt_of_a_failed_run_is_refused_not_re_spent() -> None:
    """Terminal runs are final (#146): the store refuses, and nothing is spent.

    Before the memory store grew 0004's terminal guard, this second attempt
    quietly ran to ``failed`` again — a path Postgres never allowed, which is
    exactly how #146 hid from every unit-level test.
    """
    payload = sample_payload(modes=["kpi"])
    request = request_from_payload({**payload, "max_calls": 2})
    evidence = _evidence_from_payload(payload)
    persist = MemoryPersistStore()
    checkpoint = MemoryCheckpointStore()
    llm = CountingLLM()

    def attempt() -> WorkflowState:
        return run_extraction_workflow(
            WorkflowState(request=request, evidence=list(evidence)),
            WorkflowDeps(
                structured_llm=llm,  # type: ignore[arg-type]
                checkpoint=checkpoint,
                events=MemoryEventStore(),
                persist=persist,
                evidence_loader=lambda _r: list(evidence),
            ),
        )

    first = attempt()
    assert first.status == "failed"
    assert persist.run_status[request.run_id] == "failed"
    calls_after_first = llm.calls

    with pytest.raises(RunAlreadyTerminal) as refused:
        attempt()
    assert refused.value.status == "failed"
    assert llm.calls == calls_after_first, "a refused attempt still spent model calls"
    assert persist.run_status[request.run_id] == "failed"
