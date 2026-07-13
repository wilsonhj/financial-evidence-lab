"""T0102/T0105/T0106: raw store, idempotent versioned jobs, atomic corpus
publication, and quarantine — against a real Postgres with migrations."""

from __future__ import annotations

import os
import pathlib
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from fel_providers.mocks import MockStorageProvider
from fel_workers.ingestion.pipeline import (
    active_corpus_version,
    create_corpus_version,
    ingest_filing,
    publish_corpus_version,
)
from fel_workers.ingestion.raw_store import content_address, store_raw_document

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)

pytestmark = requires_db

ENTITY = str(uuid.uuid4())
PUBLISHED = datetime(2026, 5, 5, 16, 30, tzinfo=UTC)


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in (
        "documents",
        "document_versions",
        "sections",
        "source_spans",
        "tables_meta",
        "financial_facts",
        "ingestion_runs",
        "ingestion_quarantine",
    ):
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        out[table] = int(row[0]) if row else 0
    return out


def _ingest(conn: psycopg.Connection, storage: MockStorageProvider, **overrides):
    params = {
        "entity_id": ENTITY,
        "accession": "0009999999-26-000010",
        "source_url": "https://example.invalid/synthetic_10q.html",
        "raw": fixture_bytes("synthetic_10q.html"),
        "published_at": PUBLISHED,
        "form": "10-Q",
    }
    params.update(overrides)
    return ingest_filing(conn, storage, **params)


def test_raw_store_is_content_addressed_and_immutable(corpus_conn: psycopg.Connection) -> None:
    storage = MockStorageProvider()
    raw = fixture_bytes("synthetic_10q.html")
    content_hash, storage_key = content_address(raw)
    assert content_hash.startswith("sha256:")
    assert storage_key == f"raw/sha256/{content_hash.removeprefix('sha256:')}"
    stored = store_raw_document(
        corpus_conn,
        storage,
        entity_id=ENTITY,
        accession="0009999999-26-000010",
        source_url="https://example.invalid/synthetic_10q.html",
        raw=raw,
        published_at=PUBLISHED,
        form="10-Q",
    )
    assert stored.created is True
    assert storage.get(storage_key) == raw
    # Immutability: a different payload can never land on the same key.
    with pytest.raises(ValueError, match="immutable"):
        storage.put(storage_key, b"different bytes")
    # Replaying the same accession is idempotent, not an error.
    replay = store_raw_document(
        corpus_conn,
        storage,
        entity_id=ENTITY,
        accession="0009999999-26-000010",
        source_url="https://example.invalid/synthetic_10q.html",
        raw=raw,
        published_at=PUBLISHED,
    )
    assert replay.created is False
    assert replay.document_id == stored.document_id
    row = corpus_conn.execute(
        "SELECT content_hash, form, published_at, ingested_at FROM documents WHERE id = %s",
        (stored.document_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == content_hash
    assert row[1] == "10-Q"
    assert row[2] == PUBLISHED
    assert row[3] is not None  # ingested_at default applied


def test_ingest_persists_full_corpus_shape(corpus_conn: psycopg.Connection) -> None:
    outcome = _ingest(corpus_conn, MockStorageProvider())
    assert outcome.status == "succeeded"
    counts = _counts(corpus_conn)
    assert counts["documents"] == 1
    assert counts["document_versions"] == 1
    assert counts["sections"] == outcome.sections == 6
    assert counts["source_spans"] == outcome.spans == 13
    assert counts["tables_meta"] == outcome.tables == 1
    assert counts["financial_facts"] == outcome.facts == 6
    assert counts["ingestion_runs"] == 1
    duplicate = corpus_conn.execute(
        "SELECT count(*) FROM financial_facts WHERE duplicate_of IS NOT NULL"
    ).fetchone()
    assert duplicate is not None and duplicate[0] == 1


def test_identical_job_rerun_is_a_noop(corpus_conn: psycopg.Connection) -> None:
    storage = MockStorageProvider()
    first = _ingest(corpus_conn, storage)
    assert first.status == "succeeded"
    before = _counts(corpus_conn)
    second = _ingest(corpus_conn, storage)
    assert second.status == "noop"
    assert second.job_key == first.job_key
    assert second.document_version_id == first.document_version_id
    assert second.facts == first.facts
    assert _counts(corpus_conn) == before, "a rerun must write nothing"


def test_restatement_links_across_document_versions(corpus_conn: psycopg.Connection) -> None:
    storage = MockStorageProvider()
    _ingest(corpus_conn, storage)
    # A later synthetic filing restates consolidated revenue (1,250 -> 1,300).
    amended = (
        fixture_bytes("synthetic_10q.html")
        .replace(
            b'contextRef="d2026q1" unitRef="usd" scale="6" decimals="-6" '
            b'format="ixt:num-dot-decimal">1,250',
            b'contextRef="d2026q1" unitRef="usd" '
            b'scale="6" decimals="-6" format="ixt:num-dot-decimal">1,300',
        )
        .replace(
            b'contextRef="d2026q1" unitRef="usd" scale="6" decimals="-6">1,250',
            b'contextRef="d2026q1" unitRef="usd" scale="6" decimals="-6">1,300',
        )
    )
    outcome = _ingest(
        corpus_conn,
        storage,
        raw=amended,
        accession="0009999999-26-000011",
        published_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )
    assert outcome.status == "succeeded"
    rows = corpus_conn.execute(
        "SELECT value, restates FROM financial_facts"
        " WHERE document_version_id = %s AND restates IS NOT NULL",
        (outcome.document_version_id,),
    ).fetchall()
    assert len(rows) == 2  # canonical + duplicate presentation both restate
    assert {row[0] for row in rows} == {"1300000000"}
    restated = corpus_conn.execute(
        "SELECT value FROM financial_facts WHERE id = %s", (rows[0][1],)
    ).fetchone()
    assert restated is not None and restated[0] == "1250000000"


def test_malformed_source_is_quarantined_with_actionable_diagnostic(
    corpus_conn: psycopg.Connection,
) -> None:
    outcome = _ingest(
        corpus_conn,
        MockStorageProvider(),
        raw=fixture_bytes("corrupt_missing_context.html"),
        accession="0009999999-26-000099",
    )
    assert outcome.status == "quarantined"
    assert outcome.reason_code == "UNKNOWN_CONTEXT"
    assert outcome.diagnostic is not None and "ctx-missing" in outcome.diagnostic
    row = corpus_conn.execute(
        "SELECT reason_code, diagnostic, accession FROM ingestion_quarantine"
    ).fetchone()
    assert row is not None
    assert row[0] == "UNKNOWN_CONTEXT"
    assert "ix:header" in row[1]
    assert row[2] == "0009999999-26-000099"
    # No parsed artifacts leak out of a quarantined source.
    counts = _counts(corpus_conn)
    assert counts["document_versions"] == 0
    assert counts["sections"] == counts["source_spans"] == counts["financial_facts"] == 0
    # Re-running the identical corrupt job is also a no-op.
    rerun = _ingest(
        corpus_conn,
        MockStorageProvider(),
        raw=fixture_bytes("corrupt_missing_context.html"),
        accession="0009999999-26-000099",
    )
    assert rerun.status == "noop"
    assert rerun.reason_code == "UNKNOWN_CONTEXT"
    quarantine_count = corpus_conn.execute("SELECT count(*) FROM ingestion_quarantine").fetchone()
    assert quarantine_count is not None and quarantine_count[0] == 1


def test_corpus_publication_is_atomic_single_active(corpus_conn: psycopg.Connection) -> None:
    outcome = _ingest(corpus_conn, MockStorageProvider())
    assert outcome.document_version_id is not None
    v1 = create_corpus_version(
        corpus_conn, label="2026-05-05", document_version_ids=[outcome.document_version_id]
    )
    assert active_corpus_version(corpus_conn) is None
    publish_corpus_version(corpus_conn, v1)
    assert active_corpus_version(corpus_conn) == v1

    v2 = create_corpus_version(
        corpus_conn, label="2026-06-01", document_version_ids=[outcome.document_version_id]
    )
    publish_corpus_version(corpus_conn, v2)
    assert active_corpus_version(corpus_conn) == v2
    statuses = dict(corpus_conn.execute("SELECT id::text, status FROM corpus_versions").fetchall())
    assert statuses[v1] == "superseded"
    assert statuses[v2] == "active"
    active_count = corpus_conn.execute(
        "SELECT count(*) FROM corpus_versions WHERE is_active"
    ).fetchone()
    assert active_count is not None and active_count[0] == 1
    # Publishing a non-draft (already active/superseded) version fails closed
    # and leaves the active pointer untouched.
    with pytest.raises(ValueError, match="not a draft"):
        publish_corpus_version(corpus_conn, v1)
    assert active_corpus_version(corpus_conn) == v2
    # The single-active invariant is enforced by the database itself.
    with pytest.raises(psycopg.errors.UniqueViolation):
        corpus_conn.execute(
            "INSERT INTO corpus_versions (id, label, status, is_active)"
            " VALUES (%s, 'race', 'active', true)",
            (str(uuid.uuid4()),),
        )
