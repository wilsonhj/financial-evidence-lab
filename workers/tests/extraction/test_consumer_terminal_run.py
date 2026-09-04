"""The consumer's job/run terminal-state contract, without Postgres (#146, #204).

Terminal runs are final (integration-lead ruling on #146, Option 1): a job
whose ``extraction_runs`` row is ``succeeded`` / ``failed`` / ``cancelled``
is dead-lettered, never requeued, never re-marked running. A handler result
of ``cancelled`` is recorded as a cancelled job, never a succeeded one (#204).
Every queue write is captured here so each branch is proven in isolation; the
same contract runs against real Postgres in ``test_terminal_run_not_requeued``
and ``test_cancelled_run_job_state``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers import consumer, queue
from fel_workers.consumer import run_worker
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN, request_from_payload
from fel_workers.extraction.persist import PostgresPersistStore, RunAlreadyTerminal
from fel_workers.extraction.types import WorkflowState

from .conftest import sample_payload

TERMINAL = ("succeeded", "failed", "cancelled")
TELEMETRY = "fel_workers.extraction.telemetry"


def _claimed(payload: dict[str, Any], *, attempts: int = 1) -> queue.ClaimedJob:
    return queue.ClaimedJob(
        id="0f0f0f0f-0000-4000-8000-00000000j0b1",
        kind=JOB_KIND_EXTRACTION_RUN,
        payload=payload,
        queue="extraction",
        attempts=attempts,
        max_attempts=5,
        lease="lease",
        org_id=payload["org_id"],
    )


def _result(payload: dict[str, Any], *, status: str, error: dict[str, Any] | None) -> WorkflowState:
    state = WorkflowState(request=request_from_payload(payload), evidence=[])
    state.status = status  # type: ignore[assignment]
    state.error = error
    return state


class _Harness:
    """One claim, every queue write captured, run status scripted."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        payload: dict[str, Any],
        *,
        handler: Callable[..., Any],
        run_statuses: Iterator[str | None],
    ) -> None:
        self.payload = payload
        self.writes: dict[str, list[str]] = {
            "fail": [],
            "dead_letter": [],
            "cancel": [],
            "complete": [],
        }
        self.handler_kwargs: list[dict[str, Any]] = []
        claimed: list[queue.ClaimedJob | None] = [_claimed(payload)]

        def claim_one(conn: Any, queue: str = "extraction") -> queue.ClaimedJob | None:
            del conn, queue
            return claimed.pop() if claimed else None

        def record(name: str) -> Callable[..., bool]:
            def write(conn: Any, job: queue.ClaimedJob, message: str = "") -> bool:
                del conn, job
                self.writes[name].append(message)
                return True

            return write

        def wrapped_handler(*args: Any, **kwargs: Any) -> Any:
            self.handler_kwargs.append(kwargs)
            return handler(*args, **kwargs)

        monkeypatch.setattr(queue, "reap_stale", lambda *a, **k: 0)
        monkeypatch.setattr(queue, "claim_one", claim_one)
        for name in self.writes:
            monkeypatch.setattr(queue, name, record(name))
        monkeypatch.setattr(consumer, "handle_extraction_run", wrapped_handler)
        monkeypatch.setattr(
            PostgresPersistStore,
            "load_run_status",
            lambda self, *, run_id, org_id: next(run_statuses),
        )

    def run(self, **overrides: Any) -> int:
        kwargs: dict[str, Any] = {
            "max_iterations": 1,
            "structured_llm": MockStructuredLLMProvider(),
            "heartbeat_interval_seconds": 60.0,
            "heartbeat_connection_factory": MagicMock,
        }
        kwargs.update(overrides)
        return run_worker(
            MagicMock(),  # type: ignore[arg-type]
            MockStorageProvider(),
            MockSecClient(),
            **kwargs,
        )

    @property
    def only_write(self) -> str:
        written = [name for name, calls in self.writes.items() if calls]
        assert len(written) == 1, f"expected exactly one terminal write, got {self.writes}"
        return written[0]


def _never_called(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("handle_extraction_run must not run for a terminal run")


def _telemetry(caplog: pytest.LogCaptureFixture, event: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name == TELEMETRY and event in r.getMessage()
    ]


@pytest.mark.parametrize("terminal", TERMINAL)
def test_terminal_run_job_is_parked_to_match_the_run_before_dispatch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, terminal: str
) -> None:
    """Acceptance 1 + 5: dropped before the handler, redacted reason and telemetry."""
    payload = sample_payload()
    h = _Harness(monkeypatch, payload, handler=_never_called, run_statuses=iter([terminal]))
    with caplog.at_level(logging.INFO, logger=TELEMETRY):
        completed = h.run()

    # A `succeeded` run's job is completed, so it counts; the other two do not.
    assert completed == (1 if terminal == "succeeded" else 0)
    # The handler must never be entered. Without this the test cannot tell
    # "dropped before dispatch" from "dispatched, and _never_called's
    # AssertionError was swallowed at the job boundary, after which the
    # post-failure re-read dead-lettered anyway" — which is what it does when
    # the pre-dispatch check is removed. Found by review of #211.
    assert h.handler_kwargs == [], "the handler was entered before the drop"
    # #204: the job's terminal state must MATCH the run's. Dead-lettering all
    # three would leave a `succeeded` run with a `failed` job — reachable when a
    # worker writes the run terminal, loses its lease before `queue.complete`,
    # and the reaper redelivers.
    expected_write = {"succeeded": "complete", "cancelled": "cancel", "failed": "dead_letter"}
    assert h.only_write == expected_write[terminal]
    if terminal == "succeeded":
        # `complete` is the ordinary success write and carries no reason string;
        # the run row already holds the outcome.
        assert h.writes["complete"], h.writes
    else:
        reason = h.writes[expected_write[terminal]][0]
        assert payload["run_id"] in reason and terminal in reason
        assert "Example SaaS" not in reason, "issuer text leaked into the durable job error"
        assert "terminal extraction run cannot be mutated" not in reason
    events = _telemetry(caplog, "terminal_run_job_parked")
    assert len(events) == 1, caplog.text
    for field in (
        payload["run_id"],
        "0f0f0f0f-0000-4000-8000-00000000j0b1",
        terminal,
        "'attempt': 1",
    ):
        assert field in events[0], events[0]
    assert "Example SaaS" not in events[0] and "evidence" not in events[0]


def test_run_turning_terminal_under_us_is_parked_to_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """The store's typed refusal (race after the pre-dispatch read) is not a retry.

    And the write still matches the run's status rather than defaulting to a
    dead-letter, which is the same #204 agreement rule as the pre-dispatch path.
    """
    payload = sample_payload()

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise RunAlreadyTerminal(run_id=payload["run_id"], status="cancelled")

    h = _Harness(monkeypatch, payload, handler=refuse, run_statuses=iter(["running"]))
    assert h.run() == 0
    # The refusal carries status="cancelled", so the job is cancelled to match
    # the run rather than dead-lettered as failed (#204).
    assert h.only_write == "cancel"
    assert "cancelled" in h.writes["cancel"][0]


def test_untyped_escape_after_the_run_went_terminal_is_dead_lettered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workflow's catch-all lands the row failed then re-raises: no requeue."""
    payload = sample_payload()

    def explode(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("injected crash")

    h = _Harness(monkeypatch, payload, handler=explode, run_statuses=iter(["running", "failed"]))
    assert h.run() == 0
    assert h.only_write == "dead_letter"
    assert "injected crash" in h.writes["dead_letter"][0]


def test_untyped_escape_with_a_resumable_run_still_requeues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 4: a run still ``running`` (process death, lost connection) keeps
    its retry so crash-resume works exactly as before."""
    payload = sample_payload()

    def explode(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("connection reset")

    h = _Harness(monkeypatch, payload, handler=explode, run_statuses=iter(["running", "running"]))
    assert h.run() == 0
    assert h.only_write == "fail"


def test_status_read_failure_is_not_a_reason_to_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the terminal-status read itself fails, fall back to the retry path."""
    payload = sample_payload()

    def explode(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("connection reset")

    def broken(*_a: Any, **_k: Any) -> str | None:
        raise RuntimeError("status read failed")

    h = _Harness(monkeypatch, payload, handler=explode, run_statuses=iter(["running"]))
    monkeypatch.setattr(PostgresPersistStore, "load_run_status", broken)
    assert h.run() == 0
    assert h.only_write == "fail"


def test_failed_result_is_dead_lettered_not_requeued(monkeypatch: pytest.MonkeyPatch) -> None:
    """A workflow that returned ``failed`` has already written the run terminal."""
    payload = sample_payload()
    error = {"code": "budget_exceeded", "message": "max_calls 10 reached"}
    h = _Harness(
        monkeypatch,
        payload,
        handler=lambda *a, **k: _result(payload, status="failed", error=error),
        run_statuses=iter(["queued"]),
    )
    assert h.run() == 0
    assert h.only_write == "dead_letter"
    assert "max_calls 10 reached" in h.writes["dead_letter"][0]


def test_cancelled_result_is_recorded_cancelled_not_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#204: the ``cancelled`` terminal maps to ``queue.cancel``, never ``complete``."""
    payload = sample_payload()
    error = {"code": "cancelled", "message": "run cancelled at stage boundary"}
    h = _Harness(
        monkeypatch,
        payload,
        handler=lambda *a, **k: _result(payload, status="cancelled", error=error),
        run_statuses=iter(["queued"]),
    )
    assert h.run() == 0
    assert h.only_write == "cancel"
    assert "cancelled" in h.writes["cancel"][0]


def test_cancel_check_is_forwarded_to_the_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The consumer owns the cancel signal; the handler only sees a bool hook."""
    payload = sample_payload()
    seen: list[queue.ClaimedJob] = []

    def cancel_check(job: queue.ClaimedJob) -> bool:
        seen.append(job)
        return True

    h = _Harness(
        monkeypatch,
        payload,
        handler=lambda *a, **k: _result(payload, status="waiting_review", error=None),
        run_statuses=iter(["queued"]),
    )
    assert h.run(cancel_check=cancel_check) == 1
    hook = h.handler_kwargs[0]["cancel_check"]
    assert hook is not None and hook() is True
    assert seen and seen[0].id == "0f0f0f0f-0000-4000-8000-00000000j0b1"
    assert h.only_write == "complete"


def test_memory_store_path_never_consults_the_run_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """``extraction_memory_stores`` has no durable row to be terminal."""
    payload = sample_payload()

    def must_not_read(*_a: Any, **_k: Any) -> str | None:
        raise AssertionError("memory path read the run row")

    h = _Harness(
        monkeypatch,
        payload,
        handler=lambda *a, **k: _result(payload, status="waiting_review", error=None),
        run_statuses=iter([]),
    )
    monkeypatch.setattr(PostgresPersistStore, "load_run_status", must_not_read)
    assert h.run(extraction_memory_stores=True) == 1
    assert h.only_write == "complete"
