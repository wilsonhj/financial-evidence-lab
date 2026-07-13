"""SKIP LOCKED queue semantics: claim, idempotent enqueue, retry, reaping."""

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


def test_enqueue_idempotent(conn: psycopg.Connection) -> None:
    first = queue.enqueue(conn, kind="sync", payload={"cik": "1"}, idempotency_key="job-key-0001")
    second = queue.enqueue(conn, kind="sync", payload={"cik": "1"}, idempotency_key="job-key-0001")
    assert first == second


def test_claim_run_complete(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="sync", payload={"n": 1}, queue="ingestion")
    job = queue.claim_one(conn, queue="ingestion")
    assert job is not None and job.kind == "sync" and job.attempts == 1
    assert queue.claim_one(conn, queue="ingestion") is None
    queue.heartbeat(conn, job.id)
    queue.complete(conn, job.id)
    status = conn.execute("SELECT status FROM jobs WHERE id = %s", (job.id,)).fetchone()
    assert status is not None and status[0] == "succeeded"


def test_fail_requeues_until_max_attempts(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="flaky", payload={}, max_attempts=2)
    job = queue.claim_one(conn)
    assert job is not None
    queue.fail(conn, job, "boom")
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
    job2 = queue.claim_one(conn)
    assert job2 is not None and job2.attempts == 2
    queue.fail(conn, job2, "boom again")
    row = conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row[0] == "failed" and row[1]["error"]["code"] == "JOB_FAILED"


def test_reap_stale(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="stuck", payload={})
    job = queue.claim_one(conn)
    assert job is not None
    conn.execute(
        "UPDATE jobs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (job.id,),
    )
    assert queue.reap_stale(conn) == 1
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
