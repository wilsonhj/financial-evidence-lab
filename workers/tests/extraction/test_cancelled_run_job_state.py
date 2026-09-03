"""A cancelled extraction run is recorded as a cancelled job, never succeeded (#204).

``handle_extraction_run`` returns ``status == "cancelled"`` when the workflow
observes the cancel hook at a stage boundary. The consumer used to
special-case only ``failed``, so that outcome fell through to
``queue.complete`` and the job row read ``succeeded`` while the run row read
``cancelled``. Proven end to end on real Postgres: cancellation requested
mid-run through the consumer's ``cancel_check`` hook, both rows agree, no
proposals persisted, ``run_cancelled`` is the run's last event.

Runs against the isolated ``<db>_extraction`` sibling (see
``test_postgres_crash_resume``): durable run rows are permanent.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers import queue
from fel_workers.consumer import run_worker
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN

from .test_dispatch_durability import _payload, _seeded_run
from .test_postgres_crash_resume import _ORG, ensure_extraction_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


@requires_db
@pytest.mark.parametrize("cancel_on_check", [1, 3])
def test_cancellation_mid_run_agrees_on_job_and_run_rows(
    extraction_db_url: str, cancel_on_check: int
) -> None:
    """Cancel at the first boundary (nothing committed) and after real stage work."""
    checks: list[str] = []

    def cancel_check(job: queue.ClaimedJob) -> bool:
        checks.append(job.id)
        return len(checks) >= cancel_on_check

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        request = _seeded_run(conn)
        job_id = queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=_payload(request),
            queue="extraction",
            org_id=_ORG,
            max_attempts=5,
        )
        completed = run_worker(
            conn,
            MockStorageProvider(),
            MockSecClient(),
            queue_name="extraction",
            max_iterations=3,
            structured_llm=MockStructuredLLMProvider(),
            cancel_check=cancel_check,
        )
        job = conn.execute(
            "SELECT status, attempts, finished_at, error FROM jobs WHERE id = %s", (job_id,)
        ).fetchone()
        run = conn.execute(
            "SELECT status, finished_at, error FROM extraction_runs WHERE id = %s",
            (request.run_id,),
        ).fetchone()
        proposals = conn.execute(
            "SELECT count(*) FROM extraction_proposals WHERE run_id = %s", (request.run_id,)
        ).fetchone()
        events = [
            row[0]
            for row in conn.execute(
                "SELECT event_type FROM extraction_run_events WHERE run_id = %s ORDER BY id",
                (request.run_id,),
            ).fetchall()
        ]

    assert completed == 0, "a cancelled run was counted as completed"
    assert checks and set(checks) == {job_id}, "the hook did not see the claimed job"
    assert job is not None and run is not None and proposals is not None
    assert job[0] == "cancelled", f"job row disagrees with the cancelled run: {job}"
    assert job[0] != "succeeded"
    assert job[1] == 1, "cancellation re-entered the retry loop"
    assert job[2] is not None
    assert job[3]["error"]["code"] == "JOB_CANCELLED"
    assert "cancelled" in job[3]["error"]["message"]
    assert run[0] == "cancelled", run
    assert run[1] is not None
    assert run[2]["code"] == "cancelled"
    assert proposals[0] == 0, "a cancelled run persisted proposals"
    assert "run_started" in events
    assert events[-1] == "run_cancelled", events
