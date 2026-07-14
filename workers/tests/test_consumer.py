"""Finding 4: the job consumer — claim/lease/heartbeat/complete/fail
dispatch over the Postgres queue, closing the discovery -> fetch -> ingest
loop against a real database with the committed synthetic fixtures."""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import uuid

import psycopg
import pytest

from fel_providers.mocks import MockStorageProvider
from fel_workers import queue
from fel_workers.consumer import entity_id_for_cik, handle_sec_filing_fetch, run_worker
from fel_workers.ingestion.discovery import (
    JOB_KIND_SEC_DISCOVERY,
    JOB_KIND_SEC_FILING_FETCH,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)

pytestmark = requires_db


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FixtureSecClient:
    """SecClient over committed synthetic fixtures — nothing live, ever."""

    def submissions(self, cik: str) -> dict[str, object]:
        payload = json.loads(fixture_bytes("sec_submissions_synthetic.json"))
        assert isinstance(payload, dict)
        return payload

    def fetch_document(self, url: str) -> bytes:
        return fixture_bytes("synthetic_10q.html")


class ExplodingSecClient(FixtureSecClient):
    def fetch_document(self, url: str) -> bytes:
        raise RuntimeError("synthetic transport failure")


def test_entity_id_for_cik_is_deterministic() -> None:
    assert entity_id_for_cik("9999999") == entity_id_for_cik("CIK0009999999")
    assert entity_id_for_cik("9999999") != entity_id_for_cik("1234567")


def test_worker_drains_discovery_then_fetch_jobs(corpus_conn: psycopg.Connection) -> None:
    """End-to-end over the queue: one discovery job fans out into fetch jobs,
    the worker claims each with a lease and completes it, and every fetched
    filing lands in the corpus via the idempotent pipeline."""
    storage = MockStorageProvider()
    queue.enqueue(
        corpus_conn,
        kind=JOB_KIND_SEC_DISCOVERY,
        payload={"cik": "9999999"},
        queue="ingestion",
        idempotency_key="sec-discovery|9999999",
    )
    completed = run_worker(
        corpus_conn, storage, FixtureSecClient(), queue_name="ingestion", max_iterations=10
    )
    assert completed == 4  # discovery + three discovered filings
    statuses = corpus_conn.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall()
    assert dict(statuses) == {"succeeded": 4}
    leases = corpus_conn.execute("SELECT count(*) FROM jobs WHERE lease IS NOT NULL").fetchone()
    assert leases is not None and leases[0] == 0, "completed jobs release their lease"
    documents = corpus_conn.execute(
        "SELECT count(*) FROM documents WHERE entity_id = %s",
        (entity_id_for_cik("9999999"),),
    ).fetchone()
    assert documents is not None and documents[0] == 3, "one document per accession"
    versions = corpus_conn.execute(
        "SELECT count(*) FROM document_versions WHERE status = 'parsed'"
    ).fetchone()
    assert versions is not None and versions[0] == 3

    # Draining again is a no-op: discovery re-enqueue is idempotent and the
    # ingestion ledger replays recorded results without writing.
    queue.enqueue(
        corpus_conn,
        kind=JOB_KIND_SEC_DISCOVERY,
        payload={"cik": "9999999"},
        queue="ingestion",
        idempotency_key="sec-discovery|9999999-second",
    )
    run_worker(corpus_conn, storage, FixtureSecClient(), queue_name="ingestion", max_iterations=10)
    documents_after = corpus_conn.execute("SELECT count(*) FROM documents").fetchone()
    assert documents_after is not None and documents_after[0] == 3


def test_unknown_job_kind_fails_the_job(corpus_conn: psycopg.Connection) -> None:
    queue.enqueue(
        corpus_conn,
        kind="mystery_kind",
        payload={},
        queue="ingestion",
        max_attempts=1,
    )
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        FixtureSecClient(),
        queue_name="ingestion",
        max_iterations=3,
    )
    assert completed == 0
    row = corpus_conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert "unknown job kind" in row[1]["error"]["message"]


def test_handler_exception_requeues_until_attempts_exhausted(
    corpus_conn: psycopg.Connection,
) -> None:
    """A crashing handler is a queue.fail, not a worker crash: the job is
    retried up to max_attempts, then parked as failed with the error."""
    queue.enqueue(
        corpus_conn,
        kind=JOB_KIND_SEC_FILING_FETCH,
        payload={
            "cik": "9999999",
            "accession": "0009999999-26-000010",
            "form": "10-Q",
            "filed_on": "2026-05-05",
            "url": "https://example.invalid/doc.htm",
        },
        queue="ingestion",
        max_attempts=2,
    )
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        ExplodingSecClient(),
        queue_name="ingestion",
        max_iterations=5,
    )
    assert completed == 0
    row = corpus_conn.execute("SELECT status, attempts, error FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == 2
    assert "synthetic transport failure" in row[2]["error"]["message"]


def test_fetch_payload_validation_fails_closed(corpus_conn: psycopg.Connection) -> None:
    with pytest.raises(ValueError, match="url/accession/cik"):
        handle_sec_filing_fetch(
            corpus_conn, MockStorageProvider(), FixtureSecClient(), {"cik": "9999999"}
        )


# --- Lease-contract regression tests (re-review finding 1) -----------------
#
# The consumer must heartbeat continuously while a handler runs (so a slow
# job is never reaped) and must itself reap stale claims (so a crashed
# worker's job does not stay 'running' forever). Losing the lease mid-job
# means the result is discarded, never completed.

_FETCH_PAYLOAD = {
    "cik": "9999999",
    "accession": "0009999999-26-000010",
    "form": "10-Q",
    "filed_on": "2026-05-05",
    "url": "https://example.invalid/doc.htm",
}


class SlowSecClient(FixtureSecClient):
    """Handler that runs longer than the (shortened) stale threshold."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay_seconds = delay_seconds

    def fetch_document(self, url: str) -> bytes:
        time.sleep(self._delay_seconds)
        return super().fetch_document(url)


def test_slow_handler_survives_reaper_thanks_to_heartbeats(
    corpus_conn: psycopg.Connection,
) -> None:
    """A handler slower than the stale threshold is NOT reaped: the
    background heartbeat thread keeps the claim fresh, so an aggressive
    concurrent reaper never sees it as stale."""
    db_url = os.environ["TEST_DATABASE_URL"]
    queue.enqueue(corpus_conn, kind=JOB_KIND_SEC_FILING_FETCH, payload=_FETCH_PAYLOAD)
    stop_reaping = threading.Event()
    reaped_total = 0

    def aggressive_reaper() -> None:
        nonlocal reaped_total
        with psycopg.connect(db_url, autocommit=True) as reaper_conn:
            while not stop_reaping.wait(0.1):
                reaped_total += queue.reap_stale(reaper_conn, stale_seconds=0.5)

    reaper = threading.Thread(target=aggressive_reaper, daemon=True)
    reaper.start()
    try:
        completed = run_worker(
            corpus_conn,
            MockStorageProvider(),
            SlowSecClient(delay_seconds=1.2),  # > the reaper's 0.5s threshold
            queue_name="default",
            max_iterations=2,
            heartbeat_interval_seconds=0.1,  # << 0.5s: keeps the claim fresh
        )
    finally:
        stop_reaping.set()
        reaper.join()
    assert completed == 1
    assert reaped_total == 0, "heartbeats must keep the running claim fresh"
    row = corpus_conn.execute("SELECT status, attempts FROM jobs").fetchone()
    assert row is not None and row[0] == "succeeded" and row[1] == 1


def test_crashed_workers_stale_claim_is_reaped_and_reclaimed(
    corpus_conn: psycopg.Connection,
) -> None:
    """A job whose worker crashed (claimed, never heartbeat again) is reaped
    by the run loop and completes under the new worker's lease; the zombie's
    late terminal write is fenced out."""
    db_url = os.environ["TEST_DATABASE_URL"]
    queue.enqueue(corpus_conn, kind=JOB_KIND_SEC_FILING_FETCH, payload=_FETCH_PAYLOAD)
    with psycopg.connect(db_url, autocommit=True) as crashed_conn:
        crashed_claim = queue.claim_one(crashed_conn)
    assert crashed_claim is not None
    # The worker died: no heartbeat ever again. Advance past the threshold.
    corpus_conn.execute(
        "UPDATE jobs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
        (crashed_claim.id,),
    )
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        FixtureSecClient(),
        queue_name="default",
        max_iterations=3,
        heartbeat_interval_seconds=0.1,
    )
    assert completed == 1, "the loop's reap_stale must requeue the abandoned job"
    row = corpus_conn.execute("SELECT status, attempts FROM jobs").fetchone()
    assert row is not None and row[0] == "succeeded" and row[1] == 2
    # The zombie worker coming back to life cannot write a terminal state.
    assert queue.complete(corpus_conn, crashed_claim) is False


class LeaseStealingSecClient(FixtureSecClient):
    """Simulates reap-and-reclaim by another worker while the handler runs:
    the running job's lease is replaced mid-fetch, then the handler lingers
    long enough for a heartbeat to observe the loss."""

    def __init__(self, db_url: str) -> None:
        self._db_url = db_url

    def fetch_document(self, url: str) -> bytes:
        with psycopg.connect(self._db_url, autocommit=True) as thief:
            thief.execute(
                "UPDATE jobs SET lease = %s, heartbeat_at = now() WHERE status = 'running'",
                (str(uuid.uuid4()),),
            )
        time.sleep(0.5)  # several 0.1s heartbeat intervals: the loss is seen
        return super().fetch_document(url)


def test_lease_lost_mid_job_result_is_discarded(corpus_conn: psycopg.Connection) -> None:
    """Losing the lease mid-job means the original worker must NOT mark the
    job complete — the new owner's claim stays untouched."""
    db_url = os.environ["TEST_DATABASE_URL"]
    queue.enqueue(corpus_conn, kind=JOB_KIND_SEC_FILING_FETCH, payload=_FETCH_PAYLOAD)
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        LeaseStealingSecClient(db_url),
        queue_name="default",
        max_iterations=1,
        heartbeat_interval_seconds=0.1,
    )
    assert completed == 0, "a worker that lost its lease must not complete the job"
    row = corpus_conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "running", "the new owner's claim must remain untouched"
    assert row[1] is None, "no terminal error may be written by the fenced-out worker"
