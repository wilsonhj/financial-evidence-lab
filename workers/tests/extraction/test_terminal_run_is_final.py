"""A job whose run is already terminal must be dead-lettered, not retried (#146).

Migration 0004 makes a terminal run final in the strongest sense a schema can:
``fel_guard_extraction_run`` refuses to move a run out of
``succeeded``/``failed``/``cancelled``, ``fel_assert_extraction_run_open``
rejects every child INSERT and UPDATE on such a run, and DELETE is refused
outright. A worker handed a job for one can do nothing at all.

Left to the ordinary failure path that job burns every remaining attempt,
failing identically each time and spending real model budget before it reaches
the first guarded write, and the error it reports is whichever trigger fired
first — which reads as a database fault rather than "this run is over". Option 1
of #146 is to refuse it up front with ``queue.PermanentFailure``, which the
consumer dead-letters.

The Postgres cases are gated because a memory store cannot reproduce the 0004
guard at all: it has no triggers, so the wrong behaviour is invisible there. The
memory case pins the exception type and message shape, which is what the
consumer branches on.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.handler import (
    TERMINAL_RUN_STATUSES,
    _assert_run_not_terminal,
    handle_extraction_run,
    request_from_payload,
)
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.queue import PermanentFailure

from .conftest import sample_payload
from .test_postgres_crash_resume import _ORG, _seed_parents, ensure_extraction_database
from .test_run_binding import _payload, _seed_run

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


# ---------------------------------------------------------------------------
# Memory stores: the exception type and its message.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(TERMINAL_RUN_STATUSES))
def test_terminal_status_raises_permanent_failure(status: str) -> None:
    payload = sample_payload()
    request = request_from_payload(payload)
    persist = MemoryPersistStore()
    persist.set_run_status(run_id=request.run_id, org_id=request.org_id, status=status)

    with pytest.raises(PermanentFailure) as excinfo:
        _assert_run_not_terminal(persist, request)

    message = str(excinfo.value)
    assert status in message
    assert request.run_id in message
    # A dead-lettered job's error is durable and operator-visible, so it must
    # carry a diagnosis and nothing from the payload.
    assert "terminal runs are final" in message
    assert payload["issuer_label"] not in message


@pytest.mark.parametrize("status", ["queued", "running", "waiting_review"])
def test_non_terminal_status_is_allowed_through(status: str) -> None:
    payload = sample_payload()
    request = request_from_payload(payload)
    persist = MemoryPersistStore()
    persist.set_run_status(run_id=request.run_id, org_id=request.org_id, status=status)

    _assert_run_not_terminal(persist, request)  # must not raise


def test_unknown_run_is_not_treated_as_terminal() -> None:
    """No row is a different failure, diagnosed elsewhere (``run_not_found``).

    Reading "no status" as terminal would dead-letter a job whose run row has
    simply not been created yet — a retryable race, not a permanent condition.
    """
    payload = sample_payload()
    _assert_run_not_terminal(MemoryPersistStore(), request_from_payload(payload))


def test_the_memory_path_still_runs_normally() -> None:
    """The guard is uniform across both paths and must not break the mock path."""
    state = handle_extraction_run(
        None,
        MockStructuredLLMProvider(),
        sample_payload(),
        use_memory_stores=True,
    )
    assert state.status == "waiting_review"


# ---------------------------------------------------------------------------
# Postgres: the guard the memory stores cannot reproduce.
# ---------------------------------------------------------------------------


@requires_db
@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_durable_terminal_run_is_refused_before_any_write(
    extraction_db_url: str, status: str
) -> None:
    """PermanentFailure, and not one row written by the refused attempt."""
    run_id = str(uuid.uuid4())
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, run_id)
        conn.execute(
            "UPDATE extraction_runs SET status = 'running', started_at = now() WHERE id = %s",
            (run_id,),
        )
        conn.execute(
            "UPDATE extraction_runs SET status = %s, finished_at = now() WHERE id = %s",
            (status, run_id),
        )

        with pytest.raises(PermanentFailure) as excinfo:
            handle_extraction_run(
                conn,
                MockStructuredLLMProvider(),
                _payload(run_id),
                job_org_id=_ORG,
            )

        after = conn.execute(
            """
            SELECT
              (SELECT status FROM extraction_runs WHERE id = %(run)s),
              (SELECT count(*) FROM extraction_run_steps WHERE run_id = %(run)s),
              (SELECT count(*) FROM extraction_run_events WHERE run_id = %(run)s),
              (SELECT count(*) FROM extraction_proposals WHERE run_id = %(run)s)
            """,
            {"run": run_id},
        ).fetchone()

    assert after is not None
    assert after[0] == status, "the refused attempt moved the run's status"
    assert after[1] == 0 and after[2] == 0 and after[3] == 0
    assert status in str(excinfo.value)


@requires_db
def test_a_still_open_run_is_not_refused(extraction_db_url: str) -> None:
    """Negative control: the guard must not block ordinary work."""
    run_id = str(uuid.uuid4())
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, run_id)
        state = handle_extraction_run(
            conn,
            MockStructuredLLMProvider(),
            _payload(run_id),
            job_org_id=_ORG,
        )
    assert state.status == "waiting_review"
