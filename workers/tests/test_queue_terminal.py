"""Unconditionally terminal, lease-fenced queue writes (#146, #204).

``queue.fail`` encodes the retry policy: it requeues until ``max_attempts``
is exhausted. A job whose extraction run is already terminal must never
re-enter that loop (0004 forbids reopening the run), and a cancelled run must
never be recorded as ``succeeded``. Both need a write that is terminal on the
first call and still refused when the lease was lost.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from fel_workers import queue

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)


@pytest.fixture()
def conn():
    assert TEST_DATABASE_URL is not None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("DELETE FROM jobs")
        yield c


def _row(conn: psycopg.Connection, job_id: str) -> tuple:
    row = conn.execute(
        "SELECT status, attempts, finished_at, lease, error FROM jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert row is not None
    return row


def test_dead_letter_is_terminal_on_the_first_attempt(conn: psycopg.Connection) -> None:
    """Unlike ``fail``, attempts left over are irrelevant: the job parks failed now."""
    queue.enqueue(conn, kind="extraction_run", payload={}, max_attempts=5)
    job = queue.claim_one(conn)
    assert job is not None and job.attempts == 1

    assert queue.dead_letter(conn, job, "run is already failed") is True

    status, attempts, finished_at, lease, error = _row(conn, job.id)
    assert status == "failed"
    assert attempts == 1, "dead-lettering must not spend the retry budget"
    assert finished_at is not None
    assert lease is None
    assert error["error"]["code"] == "JOB_DEAD_LETTERED"
    assert error["error"]["request_id"] == job.id
    assert "already failed" in error["error"]["message"]
    assert queue.claim_one(conn) is None, "a dead-lettered job must never be claimable again"


def test_cancel_is_terminal_and_never_reads_succeeded(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="extraction_run", payload={}, max_attempts=5)
    job = queue.claim_one(conn)
    assert job is not None

    assert queue.cancel(conn, job, "run cancelled at stage boundary") is True

    status, attempts, finished_at, lease, error = _row(conn, job.id)
    assert status == "cancelled"
    assert attempts == 1
    assert finished_at is not None
    assert lease is None
    assert error["error"]["code"] == "JOB_CANCELLED"
    assert error["error"]["request_id"] == job.id
    assert "cancelled" in error["error"]["message"]
    assert queue.claim_one(conn) is None


@pytest.mark.parametrize("write", ["dead_letter", "cancel"])
def test_terminal_writes_are_lease_fenced(conn: psycopg.Connection, write: str) -> None:
    """A reaped worker's late terminal write is refused, like ``complete``/``fail``."""
    queue.enqueue(conn, kind="extraction_run", payload={})
    stale = queue.claim_one(conn)
    assert stale is not None
    conn.execute(
        "UPDATE jobs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (stale.id,),
    )
    assert queue.reap_stale(conn) == 1
    fresh = queue.claim_one(conn)
    assert fresh is not None and fresh.lease != stale.lease

    assert getattr(queue, write)(conn, stale, "late terminal write") is False

    status, _attempts, finished_at, lease, error = _row(conn, stale.id)
    assert status == "running", "the zombie's write disturbed the new claim"
    assert finished_at is None
    assert lease == fresh.lease
    assert error is None


@pytest.mark.parametrize("write", ["dead_letter", "cancel"])
def test_terminal_writes_redact_the_stored_reason(conn: psycopg.Connection, write: str) -> None:
    """Same durable-error policy as ``fail``: credential shapes masked, ids kept."""
    queue.enqueue(conn, kind="extraction_run", payload={})
    job = queue.claim_one(conn)
    assert job is not None
    reason = (
        "run 0f0f0f0f-0000-4000-8000-000000000001 is already failed; "
        "Authorization: Bearer top-secret; api_key='sk-live-abcdef'"
    )

    assert getattr(queue, write)(conn, job, reason) is True

    stored = _row(conn, job.id)[4]["error"]["message"]
    assert "top-secret" not in stored
    assert "sk-live-abcdef" not in stored
    assert "0f0f0f0f-0000-4000-8000-000000000001" in stored
