"""Finding 4: the job consumer — claim/lease/heartbeat/complete/fail
dispatch over the Postgres queue, closing the discovery -> fetch -> ingest
loop against a real database with the committed synthetic fixtures."""

from __future__ import annotations

import json
import os
import pathlib

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
