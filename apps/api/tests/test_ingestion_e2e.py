"""Finding 4 end-to-end: enqueue -> consumer claim -> ingest -> publish ->
evidence visible through the read-only corpus API. Everything runs against
the committed SYNTHETIC fixtures and a real Postgres; nothing live."""

from __future__ import annotations

import json
import pathlib
import re

import psycopg
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from fel_providers.mocks import MockStorageProvider
from fel_workers import queue
from fel_workers.consumer import entity_id_for_cik, run_worker
from fel_workers.ingestion.discovery import JOB_KIND_SEC_DISCOVERY
from fel_workers.ingestion.pipeline import (
    active_corpus_version,
    create_corpus_version,
    publish_corpus_version,
)
from tests.conftest import requires_db

pytestmark = requires_db

FIXTURES = pathlib.Path(__file__).parents[3] / "workers" / "tests" / "fixtures"

# FK-safe deletion order: this test uses the fixture's fixed accessions, so
# it starts from a clean corpus + queue slate to stay rerun-safe.
_TABLES = (
    "corpus_version_documents",
    "corpus_versions",
    "financial_facts",
    "tables_meta",
    "source_spans",
    "sections",
    "document_versions",
    "ingestion_runs",
    "ingestion_quarantine",
    "documents",
    "jobs",
)


class FixtureSecClient:
    """SecClient over committed synthetic fixtures — no live host, ever."""

    def submissions(self, cik: str) -> dict[str, object]:
        payload = json.loads((FIXTURES / "sec_submissions_synthetic.json").read_bytes())
        assert isinstance(payload, dict)
        return payload

    def fetch_document(self, url: str) -> bytes:
        return (FIXTURES / "synthetic_10q.html").read_bytes()


def test_enqueue_claim_ingest_publish_visible_via_api(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    entity_id = entity_id_for_cik("9999999")
    with psycopg.connect(db_url, autocommit=True) as conn:
        for table in _TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list
        queue.enqueue(
            conn,
            kind=JOB_KIND_SEC_DISCOVERY,
            payload={"cik": "9999999", "forms": ["10-Q"]},
            queue="ingestion",
            idempotency_key="sec-discovery|9999999|10-Q",
        )
        completed = run_worker(
            conn,
            MockStorageProvider(),
            FixtureSecClient(),
            queue_name="ingestion",
            max_iterations=10,
        )
        assert completed == 2  # the discovery job + the one 10-Q fetch job
        statuses = conn.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall()
        assert dict(statuses) == {"succeeded": 2}
        version_rows = conn.execute(
            "SELECT id::text FROM document_versions WHERE status = 'parsed'"
        ).fetchall()
        assert len(version_rows) == 1
        corpus_version = create_corpus_version(
            conn, label="e2e", document_version_ids=[version_rows[0][0]]
        )
        publish_corpus_version(conn, corpus_version)
        assert active_corpus_version(conn) == corpus_version
        span_row = conn.execute(
            "SELECT id::text FROM source_spans WHERE document_version_id = %s LIMIT 1",
            (version_rows[0][0],),
        ).fetchone()
        assert span_row is not None

    headers = {
        "Authorization": f"Bearer {make_mock_token(org_fixture[0], org_fixture[1], 'viewer')}"
    }
    listing = client.get(f"/v1/entities/{entity_id}/documents", headers=headers)
    assert listing.status_code == 200
    documents = listing.json()
    assert [doc["accession"] for doc in documents] == ["0009999999-26-000010"]
    assert documents[0]["form"] == "10-Q"
    assert re.match(r"^sha256:[0-9a-f]{64}$", documents[0]["content_hash"])

    by_id = client.get(f"/v1/documents/{documents[0]['id']}", headers=headers)
    assert by_id.status_code == 200
    assert by_id.json()["entity_id"] == entity_id

    span = client.get(f"/v1/source-spans/{span_row[0]}", headers=headers)
    assert span.status_code == 200
    body = span.json()
    assert re.match(r"^sha256:[0-9a-f]{64}$", body["text_hash"])
    assert body["end_char"] > body["start_char"]

    # Point-in-time: a cutoff before the synthetic filing date sees nothing.
    nothing = client.get(
        f"/v1/entities/{entity_id}/documents",
        headers=headers,
        params={"as_of": "2026-01-01T00:00:00Z"},
    )
    assert nothing.json() == []
