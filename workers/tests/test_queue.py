"""SKIP LOCKED queue semantics: claim, idempotent enqueue, retry, reaping."""

from __future__ import annotations

import os

import psycopg
import pytest

from fel_workers import queue

from .conftest import ensure_organization

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


def test_enqueue_idempotent_within_tenant_scope(conn: psycopg.Connection) -> None:
    first = queue.enqueue(conn, kind="sync", payload={"cik": "1"}, idempotency_key="job-key-0001")
    second = queue.enqueue(conn, kind="sync", payload={"cik": "1"}, idempotency_key="job-key-0001")
    assert first == second


def test_idempotency_never_collides_across_tenants_or_kinds(conn: psycopg.Connection) -> None:
    import uuid as uuid_mod

    # jobs.org_id is a real foreign key since 0009, so both tenants must exist
    # before their jobs can be enqueued.
    org_a = ensure_organization(str(uuid_mod.uuid4()), name="queue org A")
    org_b = ensure_organization(str(uuid_mod.uuid4()), name="queue org B")
    a = queue.enqueue(conn, kind="sync", payload={}, idempotency_key="shared-key-01", org_id=org_a)
    b = queue.enqueue(conn, kind="sync", payload={}, idempotency_key="shared-key-01", org_id=org_b)
    assert a != b, "two tenants reusing a client key must get distinct jobs"
    a_again = queue.enqueue(
        conn, kind="sync", payload={}, idempotency_key="shared-key-01", org_id=org_a
    )
    assert a_again == a
    other_kind = queue.enqueue(
        conn, kind="reindex", payload={}, idempotency_key="shared-key-01", org_id=org_a
    )
    assert other_kind != a


def test_claim_run_complete(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="sync", payload={"n": 1}, queue="ingestion")
    job = queue.claim_one(conn, queue="ingestion")
    assert job is not None and job.kind == "sync" and job.attempts == 1
    assert queue.claim_one(conn, queue="ingestion") is None
    assert queue.heartbeat(conn, job) is True
    assert queue.complete(conn, job) is True
    status = conn.execute("SELECT status FROM jobs WHERE id = %s", (job.id,)).fetchone()
    assert status is not None and status[0] == "succeeded"


def test_fail_requeues_until_max_attempts(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="flaky", payload={}, max_attempts=2)
    job = queue.claim_one(conn)
    assert job is not None
    assert queue.fail(conn, job, "boom") is True
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
    job2 = queue.claim_one(conn)
    assert job2 is not None and job2.attempts == 2
    assert queue.fail(conn, job2, "boom again") is True
    row = conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row[0] == "failed" and row[1]["error"]["code"] == "JOB_FAILED"


def test_fail_redacts_credentials_but_keeps_operational_identifiers(
    conn: psycopg.Connection,
) -> None:
    queue.enqueue(conn, kind="sec_filing_fetch", payload={}, max_attempts=1)
    job = queue.claim_one(conn)
    assert job is not None
    message = (
        "job kind 'sec_filing_fetch', ticker 'CRM', accession '0001-25-000001'; "
        "Authorization: Bearer top-secret; FEL_OPENAI_API_KEY=sk-live-abcdef; "
        "access_token='token with spaces'"
    )

    assert queue.fail(conn, job, message) is True

    row = conn.execute("SELECT error FROM jobs WHERE id = %s", (job.id,)).fetchone()
    assert row is not None
    stored = row[0]["error"]["message"]
    assert "top-secret" not in stored
    assert "sk-live-abcdef" not in stored
    assert "token with spaces" not in stored
    assert "sec_filing_fetch" in stored
    assert "CRM" in stored
    assert "0001-25-000001" in stored


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


def test_reaped_worker_cannot_write_terminal_state(conn: psycopg.Connection) -> None:
    """The reaper-versus-late-worker race: the stale worker's lease is fenced
    out; the re-claiming worker owns the job."""
    queue.enqueue(conn, kind="slow", payload={})
    stale_worker_job = queue.claim_one(conn)
    assert stale_worker_job is not None
    conn.execute(
        "UPDATE jobs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (stale_worker_job.id,),
    )
    assert queue.reap_stale(conn) == 1

    new_worker_job = queue.claim_one(conn)
    assert new_worker_job is not None and new_worker_job.lease != stale_worker_job.lease

    # The zombie worker finishes late: every fenced write must be a no-op.
    assert queue.complete(conn, stale_worker_job) is False
    assert queue.fail(conn, stale_worker_job, "late failure") is False
    assert queue.heartbeat(conn, stale_worker_job) is False
    status = conn.execute("SELECT status FROM jobs").fetchone()[0]
    assert status == "running", "zombie writes must not disturb the new claim"

    assert queue.complete(conn, new_worker_job) is True
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "succeeded"
