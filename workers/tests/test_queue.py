"""SKIP LOCKED queue semantics: claim, idempotent enqueue, retry, reaping."""

from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime, timedelta

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


def _elapse_backoff(conn: psycopg.Connection) -> None:
    """Pretend every scheduled retry has come due."""
    conn.execute("UPDATE jobs SET available_at = now() WHERE status = 'queued'")


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
    # The requeue is scheduled, not immediate (retry backoff, #189). This test
    # is about the attempts budget, so skip the wait explicitly rather than
    # letting an unrelated delay decide what it asserts.
    _elapse_backoff(conn)
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


# --- Retry backoff (#189) -------------------------------------------------


def test_backoff_is_exponential_capped_and_deterministic_under_injection() -> None:
    """The schedule itself is a pure function, so it is asserted exactly
    rather than through a range: with jitter's draw pinned to the midpoint
    the delay is base * factor ** (attempts - 1), capped at 15 minutes."""
    midpoint = random.Random()
    midpoint.random = lambda: 0.5  # type: ignore[method-assign]
    assert queue.backoff_seconds(1, rng=midpoint) == pytest.approx(5.0)
    assert queue.backoff_seconds(2, rng=midpoint) == pytest.approx(10.0)
    assert queue.backoff_seconds(3, rng=midpoint) == pytest.approx(20.0)
    # 5 * 2**19 is far past the cap; the cap holds, and holds under jitter.
    assert queue.backoff_seconds(20, rng=midpoint) == pytest.approx(900.0)
    lowest = random.Random()
    lowest.random = lambda: 0.0  # type: ignore[method-assign]
    highest = random.Random()
    highest.random = lambda: 1.0  # type: ignore[method-assign]
    assert queue.backoff_seconds(3, rng=lowest) == pytest.approx(15.0)  # -25%
    assert queue.backoff_seconds(3, rng=highest) == pytest.approx(25.0)  # +25%
    assert queue.backoff_seconds(20, rng=highest) == pytest.approx(900.0)
    # A seeded RNG reproduces exactly, which is what the tests above rely on.
    assert queue.backoff_seconds(4, rng=random.Random(7)) == queue.backoff_seconds(
        4, rng=random.Random(7)
    )


def test_fail_schedules_available_at_in_the_future_and_claim_skips_it(
    conn: psycopg.Connection,
) -> None:
    """A non-terminal failure requeues the job but does NOT hand it straight
    back: before #189 the retry ran again in the same millisecond, so a
    transient dependency burned the whole attempts budget instantly."""
    queue.enqueue(conn, kind="flaky", payload={}, max_attempts=5)
    job = queue.claim_one(conn)
    assert job is not None

    before = datetime.now(UTC)
    assert queue.fail(conn, job, "transient upstream error") is True

    row = conn.execute("SELECT status, available_at FROM jobs").fetchone()
    assert row is not None
    status, available_at = row
    assert status == "queued"
    assert available_at > before, "a requeued attempt must be scheduled forward"
    # base 5s +/- 25% jitter, measured from the fail() moment.
    assert available_at <= before + timedelta(seconds=7)

    assert queue.claim_one(conn) is None, "a backed-off job must not be claimable"
    _elapse_backoff(conn)
    assert queue.claim_one(conn) is not None, "it must be claimable once due"


def test_fail_backoff_instant_is_exact_when_now_and_rng_are_injected(
    conn: psycopg.Connection,
) -> None:
    queue.enqueue(conn, kind="flaky", payload={}, max_attempts=5)
    job = queue.claim_one(conn)
    assert job is not None
    frozen = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    midpoint = random.Random()
    midpoint.random = lambda: 0.5  # type: ignore[method-assign]

    assert queue.fail(conn, job, "boom", now=frozen, rng=midpoint) is True

    row = conn.execute("SELECT available_at FROM jobs").fetchone()
    assert row is not None
    assert row[0] == frozen + timedelta(seconds=5)


def test_terminal_failure_is_not_rescheduled(conn: psycopg.Connection) -> None:
    """The last attempt parks the job; backoff on a dead job would only make
    a 'failed' row look like it were still coming back."""
    queue.enqueue(conn, kind="flaky", payload={}, max_attempts=1)
    job = queue.claim_one(conn)
    assert job is not None
    assert queue.fail(conn, job, "final boom") is True
    row = conn.execute("SELECT status, available_at, finished_at FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[2] is not None
    assert row[1] <= datetime.now(UTC)


# --- Reaping an exhausted claim (#189) ------------------------------------


def _make_stale(conn: psycopg.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (job_id,),
    )


def test_reap_dead_letters_a_stale_claim_with_no_attempts_left(
    conn: psycopg.Connection,
) -> None:
    """THE poison-job bug (#189 finding 1): a job that reliably kills its
    worker used to be reaped, re-claimed and killed again forever, because
    reap_stale requeued every stale row with no attempts check."""
    queue.enqueue(conn, kind="poison", payload={}, max_attempts=1)
    job = queue.claim_one(conn)
    assert job is not None and job.attempts == job.max_attempts
    _make_stale(conn, job.id)

    outcome = queue.reap_stale(conn)

    assert outcome == 1  # int-compatible for existing callers
    assert outcome.requeued == 0
    assert outcome.dead_lettered == 1
    row = conn.execute("SELECT status, error, lease, finished_at FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "failed", "an exhausted stale job must not be reaped again"
    assert row[1]["error"]["code"] == "REAPED_EXHAUSTED"
    assert row[1]["error"]["request_id"] == job.id
    assert row[2] is None and row[3] is not None
    assert queue.claim_one(conn) is None, "a dead-lettered job is not re-claimable"


def test_reap_requeues_a_stale_claim_with_attempts_left(conn: psycopg.Connection) -> None:
    queue.enqueue(conn, kind="stuck", payload={}, max_attempts=3)
    job = queue.claim_one(conn)
    assert job is not None and job.attempts == 1
    _make_stale(conn, job.id)

    outcome = queue.reap_stale(conn)

    assert outcome.requeued == 1
    assert outcome.dead_lettered == 0
    row = conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row is not None and row[0] == "queued"
    assert row[1] is None, "a recoverable reap must not write a terminal error"
    # Requeued immediately: the attempt never ran, so there is nothing
    # transient to wait out.
    assert queue.claim_one(conn) is not None


def test_reap_splits_a_mixed_batch(conn: psycopg.Connection) -> None:
    """One sweep, both outcomes: the counts must not be inferred from rowcount."""
    for _ in range(2):
        queue.enqueue(conn, kind="poison", payload={}, max_attempts=1)
    queue.enqueue(conn, kind="stuck", payload={}, max_attempts=5)
    for _ in range(3):
        job = queue.claim_one(conn)
        assert job is not None
        _make_stale(conn, job.id)

    outcome = queue.reap_stale(conn)

    assert (outcome.requeued, outcome.dead_lettered) == (1, 2)
    assert int(outcome) == 3
    statuses = dict(conn.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall())
    assert statuses == {"queued": 1, "failed": 2}


# --- Permanent failure and cancellation (#189/#146) -----------------------


def test_dead_letter_parks_on_the_first_attempt(conn: psycopg.Connection) -> None:
    """PermanentFailure means the job can never succeed, so the remaining
    attempts budget is irrelevant: it is terminal now, not after five tries."""
    queue.enqueue(conn, kind="extraction_run", payload={}, max_attempts=5)
    job = queue.claim_one(conn)
    assert job is not None and job.attempts == 1

    assert queue.dead_letter(conn, job, "run 42 is already terminal") is True

    row = conn.execute("SELECT status, attempts, error, lease FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "failed" and row[1] == 1
    assert row[2]["error"]["code"] == "JOB_PERMANENT_FAILURE"
    assert row[3] is None
    assert queue.claim_one(conn) is None


def test_is_cancel_requested_observes_the_flag(conn: psycopg.Connection) -> None:
    job_id = queue.enqueue(conn, kind="extraction_run", payload={})
    assert queue.is_cancel_requested(conn, job_id=job_id) is False

    conn.execute("UPDATE jobs SET cancel_requested_at = now() WHERE id = %s", (job_id,))

    assert queue.is_cancel_requested(conn, job_id=job_id) is True
    # Cancellation is advisory: it never moves the job out of its own state,
    # so a claimed run gets to wind itself down to a consistent terminal row.
    status = conn.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert status is not None and status[0] == "queued"


def test_is_cancel_requested_is_false_for_an_unknown_job(conn: psycopg.Connection) -> None:
    assert queue.is_cancel_requested(conn, job_id=str(uuid.uuid4())) is False
