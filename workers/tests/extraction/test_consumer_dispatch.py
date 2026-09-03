"""Consumer dispatches extraction_run (M3-102)."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers import queue
from fel_workers.consumer import run_worker
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN

from ..conftest import ensure_organization
from .conftest import sample_payload
from .test_dispatch_durability import _durable_counts, _payload, _seeded_run
from .test_postgres_crash_resume import _ORG, ensure_extraction_database

requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)


class _FakeConn:
    """Minimal stand-in so dispatch tests can run without Postgres."""

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("DB not available in unit path")


def test_consumer_fails_extraction_without_structured_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown-capability path: missing structured_llm fails the job."""
    failed: list[str] = []

    monkeypatch.setattr(queue, "reap_stale", lambda *a, **k: 0)

    claimed = queue.ClaimedJob(
        id="job-1",
        kind=JOB_KIND_EXTRACTION_RUN,
        payload=sample_payload(),
        queue="ingestion",
        attempts=1,
        max_attempts=5,
        lease="lease",
    )

    def claim_one(conn: Any, queue: str = "ingestion") -> queue.ClaimedJob | None:
        del conn, queue
        nonlocal claimed
        job, claimed = claimed, None  # type: ignore[assignment]
        return job

    monkeypatch.setattr(queue, "claim_one", claim_one)
    monkeypatch.setattr(
        queue,
        "fail",
        lambda conn, job, err: failed.append(err),
    )
    monkeypatch.setattr(queue, "complete", lambda *a, **k: True)

    completed = run_worker(
        MagicMock(),  # type: ignore[arg-type]
        MockStorageProvider(),
        MockSecClient(),
        max_iterations=1,
        structured_llm=None,
    )
    assert completed == 0
    assert failed
    assert "StructuredLLMProvider" in failed[0]


@requires_db
def test_consumer_dispatches_extraction_run(corpus_conn: Any) -> None:
    """Claim-to-complete wiring for extraction_run through the real queue.

    Runs against the shared corpus database, so it cannot persist durably:
    `extraction_runs` rows are permanent under 0004 and would block every
    later suite's `DELETE FROM corpus_versions`. Memory stores are therefore
    requested explicitly — the durable path is covered in
    `test_dispatch_durability.py` against the isolated extraction sibling.
    """
    payload = sample_payload(modes=["kpi"])
    # jobs.org_id is a real foreign key since 0009; the tenant must exist.
    ensure_organization(payload["org_id"], name="dispatch org")
    queue.enqueue(
        corpus_conn,
        kind=JOB_KIND_EXTRACTION_RUN,
        payload=payload,
        queue="ingestion",
        idempotency_key=f"extraction|{payload['run_id']}",
        org_id=payload["org_id"],
    )
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        MockSecClient(),
        queue_name="ingestion",
        max_iterations=3,
        structured_llm=MockStructuredLLMProvider(),
        extraction_memory_stores=True,
    )
    assert completed == 1
    row = corpus_conn.execute(
        "SELECT status, error FROM jobs WHERE kind = %s",
        (JOB_KIND_EXTRACTION_RUN,),
    ).fetchone()
    assert row is not None
    assert row[0] == "succeeded"


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    """Isolated ``<db>_extraction`` sibling.

    The durable tests below commit real ``extraction_runs`` rows, which 0004
    makes permanent; see ``ensure_extraction_database`` for why they cannot
    share TEST_DATABASE_URL.
    """
    if os.environ.get("TEST_DATABASE_URL") is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(os.environ["TEST_DATABASE_URL"])


def _drive_cancellable(conn: psycopg.Connection, *, refuse: bool = False) -> int:
    return run_worker(
        conn,
        MockStorageProvider(),
        MockSecClient(),
        queue_name="extraction",
        max_iterations=3,
        structured_llm=MockStructuredLLMProvider(refuse=refuse),
    )


def _job_row(conn: psycopg.Connection, job_id: str) -> tuple[Any, ...]:
    row = conn.execute("SELECT status, error FROM jobs WHERE id = %s", (job_id,)).fetchone()
    assert row is not None
    return row


@requires_db
def test_cancelled_run_cancels_its_job(extraction_db_url: str) -> None:
    """A cancelled handler outcome must land the job on 'cancelled' (#204).

    ``handle_extraction_run`` can return ``status == 'cancelled'``: the
    cooperative ``cancel_check`` fires at a stage boundary and the workflow
    winds the run down to a consistent terminal state. The consumer only
    special-cased ``'failed'``, so this outcome fell through to
    ``queue.complete`` and the job read ``succeeded`` while its own run read
    ``cancelled`` — an operator cancelling a run saw the job report success.

    Cancellation is requested the way the API requests it: ``cancel_requested_at``
    on the job row (migration 0007 grants the API role exactly that column),
    never a status write.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        request = _seeded_run(conn)
        job_id = queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=_payload(request),
            queue="extraction",
            org_id=_ORG,
        )
        conn.execute("UPDATE jobs SET cancel_requested_at = now() WHERE id = %s", (job_id,))
        completed = _drive_cancellable(conn)
        job = _job_row(conn, job_id)
        durable = _durable_counts(conn, request.run_id)
        events = conn.execute(
            "SELECT event_type FROM extraction_run_events WHERE run_id = %s ORDER BY id",
            (request.run_id,),
        ).fetchall()

    assert completed == 0, "a cancelled run must not be counted as a completed job"
    assert job[0] == "cancelled", f"job terminal state disagrees with its run: {job}"
    assert str(job[1]).find("JOB_CANCELLED") >= 0, job[1]
    assert durable["run_status"] == "cancelled"
    assert durable["proposals"] == 0, "a run cancelled at the first boundary wrote proposals"
    assert events, "the cancelled run recorded no events"
    assert events[-1][0] == "run_cancelled", events


@requires_db
@pytest.mark.parametrize(
    ("outcome", "expected_job_status", "expected_run_status"),
    [
        ("succeeded", "succeeded", "waiting_review"),
        ("failed", "failed", "failed"),
        ("cancelled", "cancelled", "cancelled"),
    ],
)
def test_job_and_run_terminal_states_agree(
    extraction_db_url: str,
    outcome: str,
    expected_job_status: str,
    expected_run_status: str,
) -> None:
    """The job's verdict and its run's verdict are one outcome, not two.

    ``waiting_review`` is the workflow's successful terminal: the run finished
    its work and is waiting on a human, so the JOB is done. The other two are
    named identically on both sides. Before #204 the third row failed: the job
    said ``succeeded`` about a ``cancelled`` run.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        request = _seeded_run(conn)
        job_id = queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=_payload(request),
            queue="extraction",
            org_id=_ORG,
            # A failure must be terminal on the first claim; queue.fail would
            # otherwise requeue it and the row would read 'queued'.
            max_attempts=1,
        )
        if outcome == "cancelled":
            conn.execute("UPDATE jobs SET cancel_requested_at = now() WHERE id = %s", (job_id,))
        completed = _drive_cancellable(conn, refuse=outcome == "failed")
        job = _job_row(conn, job_id)
        durable = _durable_counts(conn, request.run_id)

    assert job[0] == expected_job_status, job
    assert durable["run_status"] == expected_run_status, durable
    assert completed == (1 if outcome == "succeeded" else 0)
