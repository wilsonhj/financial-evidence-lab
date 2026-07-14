"""Finding 4 end-to-end: enqueue -> consumer claim -> ingest -> evidence
visible through the read-only corpus API. Everything runs against the
committed SYNTHETIC fixtures and a real Postgres; nothing live.

Visibility ruling (integration lead, M1 — see apps/api/app/corpus.py):
corpus-read visibility IS "a successfully parsed version exists"; publish
(corpus_versions / the single-active pointer) deliberately does NOT gate
M1 API reads and arrives with M2's corpus-pinned retrieval. The tests
below keep those two stories separate: API visibility is asserted against
the parsed gate alone, and publish is asserted only for its own invariant
(the single-active pointer).
"""

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

# FK-safe deletion order: these tests use the fixture's fixed accessions, so
# each starts from a clean corpus + queue slate to stay rerun-safe.
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


def _ingest_synthetic_10q(conn: psycopg.Connection) -> str:
    """Clean slate, then drive discovery -> fetch -> parse through the real
    queue consumer; returns the parsed document_version id."""
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
    return str(version_rows[0][0])


def _auth_headers(org_fixture: tuple[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_mock_token(org_fixture[0], org_fixture[1], 'viewer')}"}


def test_enqueue_claim_ingest_parsed_visible_via_api(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    """End-to-end: enqueue -> consumer claim -> ingest -> parsed evidence is
    visible through the corpus API. Per the M1 visibility ruling, the gate
    asserted here is "a parsed version exists" — no corpus version is ever
    created or published in this test."""
    entity_id = entity_id_for_cik("9999999")
    with psycopg.connect(db_url, autocommit=True) as conn:
        version_id = _ingest_synthetic_10q(conn)
        span_row = conn.execute(
            "SELECT id::text FROM source_spans WHERE document_version_id = %s LIMIT 1",
            (version_id,),
        ).fetchone()
        assert span_row is not None

    headers = _auth_headers(org_fixture)
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


def test_unpublished_parsed_document_is_visible(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    """Pins the M1 visibility ruling so the story cannot silently drift:
    an UNPUBLISHED but parsed document IS visible through the corpus API.
    Publish gating of reads is explicitly out of M1 scope (it arrives with
    M2 corpus-pinned retrieval — see apps/api/app/corpus.py)."""
    entity_id = entity_id_for_cik("9999999")
    with psycopg.connect(db_url, autocommit=True) as conn:
        _ingest_synthetic_10q(conn)
        # Nothing was ever published — no corpus version even exists.
        versions = conn.execute("SELECT count(*) FROM corpus_versions").fetchone()
        assert versions is not None and versions[0] == 0
        assert active_corpus_version(conn) is None

    headers = _auth_headers(org_fixture)
    listing = client.get(f"/v1/entities/{entity_id}/documents", headers=headers)
    assert listing.status_code == 200
    documents = listing.json()
    assert [doc["accession"] for doc in documents] == ["0009999999-26-000010"]
    by_id = client.get(f"/v1/documents/{documents[0]['id']}", headers=headers)
    assert by_id.status_code == 200


def test_publish_maintains_single_active_pointer(db_url: str) -> None:
    """Publish is asserted for its OWN invariant — exactly one active corpus
    version, atomically swapped — not for API visibility, which it does not
    influence in M1 (integration-lead ruling; see apps/api/app/corpus.py)."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        version_id = _ingest_synthetic_10q(conn)
        first = create_corpus_version(conn, label="e2e-v1", document_version_ids=[version_id])
        publish_corpus_version(conn, first)
        assert active_corpus_version(conn) == first

        second = create_corpus_version(conn, label="e2e-v2", document_version_ids=[version_id])
        publish_corpus_version(conn, second)
        assert active_corpus_version(conn) == second
        active_count = conn.execute(
            "SELECT count(*) FROM corpus_versions WHERE is_active"
        ).fetchone()
        assert active_count is not None and active_count[0] == 1
        first_status = conn.execute(
            "SELECT status FROM corpus_versions WHERE id = %s", (first,)
        ).fetchone()
        assert first_status is not None and first_status[0] == "superseded"
