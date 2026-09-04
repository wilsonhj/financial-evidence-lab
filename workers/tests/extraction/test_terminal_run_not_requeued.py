"""A queue job for a terminal extraction run is dead-lettered, not retried (#146).

Integration-lead ruling (Option 1): terminal runs are final. Frozen 0004
raises ``terminal extraction run cannot be mutated`` on any update to a
``succeeded`` / ``failed`` / ``cancelled`` run row, so a queue retry against
such a row can never make progress — before this fix the consumer burned
every attempt on it, each one dying inside ``mark_running`` / the resume's
own ``run_started`` append. Proven here on real Postgres for all three
terminal states, driving ``run_worker`` end to end.

Runs against the isolated ``<db>_extraction`` sibling, for the reason
documented in ``test_postgres_crash_resume``: durable run rows are permanent.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg
import pytest

from fel_workers import queue
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN
from fel_workers.extraction.persist import PostgresPersistStore

from .test_dispatch_durability import _drive, _payload, _seeded_run
from .test_postgres_crash_resume import _ORG, ensure_extraction_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)
TERMINAL = ("succeeded", "failed", "cancelled")
TELEMETRY = "fel_workers.extraction.telemetry"


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


def _run_snapshot(conn: psycopg.Connection, run_id: str) -> tuple[Any, ...]:
    row = conn.execute(
        """
        SELECT r.status, r.started_at, r.finished_at, r.error, r.calls_used,
               (SELECT count(*) FROM extraction_run_events e WHERE e.run_id = r.id),
               (SELECT count(*) FROM extraction_run_steps s WHERE s.run_id = r.id),
               (SELECT count(*) FROM extraction_proposals p WHERE p.run_id = r.id)
          FROM extraction_runs r WHERE r.id = %s
        """,
        (run_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


@requires_db
@pytest.mark.parametrize("terminal", TERMINAL)
def test_job_for_a_terminal_run_is_parked_to_match_the_run_not_retried(
    extraction_db_url: str,
    terminal: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mark_running_calls: list[str] = []
    real_mark_running = PostgresPersistStore.mark_running

    def spy(self: PostgresPersistStore, *, run_id: str, org_id: str) -> None:
        mark_running_calls.append(run_id)
        real_mark_running(self, run_id=run_id, org_id=org_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        request = _seeded_run(conn)
        store = PostgresPersistStore(conn)
        store.mark_running(run_id=request.run_id, org_id=_ORG)
        store.set_run_status(run_id=request.run_id, org_id=_ORG, status=terminal)
        before = _run_snapshot(conn, request.run_id)

        job_id = queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=_payload(request),
            queue="extraction",
            org_id=_ORG,
            max_attempts=5,
        )
        monkeypatch.setattr(PostgresPersistStore, "mark_running", spy)
        with caplog.at_level(logging.INFO, logger=TELEMETRY):
            completed = _drive(conn)  # max_iterations=3: a requeue WOULD be re-claimed

        job = conn.execute(
            "SELECT status, attempts, finished_at, error FROM jobs WHERE id = %s", (job_id,)
        ).fetchone()
        after = _run_snapshot(conn, request.run_id)

    # #204: the job's terminal state must MATCH the run's, so the expected job
    # row differs per terminal status. Parking every one as `failed` would leave
    # a fully successful run with a permanently failed job — reachable when a
    # worker writes the run terminal, loses its lease before `queue.complete`,
    # and the reaper redelivers the job.
    expected_job_status = {"succeeded": "succeeded", "failed": "failed", "cancelled": "cancelled"}
    assert completed == (1 if terminal == "succeeded" else 0)
    assert job is not None
    status, attempts, finished_at, error = job
    assert status == expected_job_status[terminal], f"job state does not match the run: {job}"
    assert attempts == 1, "the job re-entered the retry loop"
    assert finished_at is not None
    if terminal == "succeeded":
        # `complete` is the ordinary success write and records no error.
        assert error is None, f"a completed job carries no error: {error}"
    else:
        expected_code = {"failed": "JOB_DEAD_LETTERED", "cancelled": "JOB_CANCELLED"}[terminal]
        assert error["error"]["code"] == expected_code
        message = error["error"]["message"]
        assert request.run_id in message and terminal in message
        assert "terminal extraction run cannot be mutated" not in message, "0004 was tripped"
        assert request.issuer_label not in message, "issuer text leaked into jobs.error"
    assert after == before, "the terminal run row (or its children) was touched"
    assert mark_running_calls == [], "mark_running was called on a terminal run"
    events = [
        r.getMessage()
        for r in caplog.records
        if r.name == TELEMETRY and "terminal_run_job_parked" in r.getMessage()
    ]
    assert len(events) == 1, caplog.text
    assert request.run_id in events[0] and job_id in events[0] and terminal in events[0]
    assert request.issuer_label not in events[0]


@requires_db
@pytest.mark.parametrize("terminal", TERMINAL)
def test_0004_still_refuses_a_raw_update_to_a_terminal_run(
    extraction_db_url: str, terminal: str
) -> None:
    """The trigger this whole fix front-runs is still there, and still fires.

    Every other assertion in this suite is *negative* — that
    ``terminal extraction run cannot be mutated`` never reaches a durable
    job error, because the Python guard refuses first. That is only
    meaningful while the trigger it defers to actually exists: if 0004 were
    dropped, those tests would keep passing and the last line of defence
    would be gone silently. This is the positive characterisation, taken at
    the database rather than through any store, so it fails if the migration
    changes rather than if the guard does.

    A test asserting this existed before PR #214 rewrote it to cover the
    store's typed refusal; the store-level assertion is the right one for
    that layer, but it replaced the only proof the trigger fires. Restored
    here alongside it rather than instead of it.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        request = _seeded_run(conn)
        # 0004 also enforces the transition graph, so the row cannot jump from
        # `queued` straight to a terminal state — drive it the legal way first.
        conn.execute(
            "UPDATE extraction_runs SET status = 'running', started_at = now() WHERE id = %s",
            (request.run_id,),
        )
        conn.execute(
            "UPDATE extraction_runs SET status = %s, finished_at = now() WHERE id = %s",
            (terminal, request.run_id),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="terminal extraction run"):
            conn.execute(
                "UPDATE extraction_runs SET status = 'running' WHERE id = %s",
                (request.run_id,),
            )
        still = conn.execute(
            "SELECT status FROM extraction_runs WHERE id = %s", (request.run_id,)
        ).fetchone()
        assert still is not None and still[0] == terminal, "the terminal row was mutated"
