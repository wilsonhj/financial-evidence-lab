"""T0102/T0105/T0106: raw store, idempotent versioned jobs, atomic corpus
publication, and quarantine — against a real Postgres with migrations."""

from __future__ import annotations

import hashlib
import os
import pathlib
import threading
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from fel_providers.mocks import MockStorageProvider
from fel_workers.ingestion.errors import DivergentAccessionError
from fel_workers.ingestion.parser import parse_filing
from fel_workers.ingestion.pipeline import (
    PublishConflictError,
    _prior_canonical_facts,
    active_corpus_version,
    create_corpus_version,
    ingest_filing,
    job_key,
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


def test_job_key_scopes_entity_and_accession(corpus_conn: psycopg.Connection) -> None:
    """Finding 1: byte-identical filings under a different accession (or
    entity) are DISTINCT jobs — no aliasing onto the first filing's rows."""
    hash_a = "sha256:" + "0" * 64
    base = job_key(hash_a, "p1", "n1", entity_id="e1", accession="a1")
    assert job_key(hash_a, "p1", "n1", entity_id="e1", accession="a2") != base
    assert job_key(hash_a, "p1", "n1", entity_id="e2", accession="a1") != base
    with pytest.raises(ValueError, match="delimiter"):
        job_key(hash_a, "p1", "n1", entity_id="e|1", accession="a1")

    storage = MockStorageProvider()
    first = _ingest(corpus_conn, storage)
    assert first.status == "succeeded"
    # Same bytes, new accession: a real second ingestion, not a no-op.
    second = _ingest(
        corpus_conn,
        storage,
        accession="0009999999-26-000011",
        published_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )
    assert second.status == "succeeded"
    assert second.job_key != first.job_key
    assert second.document_id != first.document_id
    assert second.document_version_id != first.document_version_id
    counts = _counts(corpus_conn)
    assert counts["documents"] == 2
    assert counts["document_versions"] == 2
    assert counts["ingestion_runs"] == 2


def test_changed_bytes_reingest_quarantines_and_preserves_provenance(
    corpus_conn: psycopg.Connection,
) -> None:
    """Finding 2: re-fetching a recorded accession with DIFFERENT bytes fails
    closed into quarantine (documented supersede-or-quarantine choice:
    quarantine). documents.content_hash keeps matching the bytes the
    published version was parsed from, and no UniqueViolation escapes."""
    storage = MockStorageProvider()
    raw = fixture_bytes("synthetic_10q.html")
    first = _ingest(corpus_conn, storage, raw=raw)
    assert first.status == "succeeded"
    original_hash, original_key = content_address(raw)

    mutated = raw.replace(b"8,400", b"9,400")
    outcome = _ingest(corpus_conn, storage, raw=mutated)
    assert outcome.status == "quarantined"
    assert outcome.reason_code == "DIVERGENT_ACCESSION_CONTENT"
    assert outcome.document_id == first.document_id
    assert outcome.document_version_id is None

    row = corpus_conn.execute(
        "SELECT content_hash, storage_key FROM documents WHERE id = %s",
        (first.document_id,),
    ).fetchone()
    assert row is not None and row[0] == original_hash and row[1] == original_key
    # Invariant: the recorded hash matches the bytes the published version
    # was parsed from — the original bytes, still immutable in storage.
    assert storage.get(original_key) == raw
    counts = _counts(corpus_conn)
    assert counts["document_versions"] == 1, "divergent bytes must not create a version"
    assert counts["ingestion_quarantine"] == 1
    quarantine = corpus_conn.execute(
        "SELECT reason_code, diagnostic, content_hash FROM ingestion_quarantine"
    ).fetchone()
    assert quarantine is not None
    assert quarantine[0] == "DIVERGENT_ACCESSION_CONTENT"
    assert "refusing to overwrite" in quarantine[1]
    assert quarantine[2] == content_address(mutated)[0]

    # The raw store itself raises the typed domain error, never a raw
    # psycopg UniqueViolation.
    with pytest.raises(DivergentAccessionError) as excinfo:
        store_raw_document(
            corpus_conn,
            storage,
            entity_id=ENTITY,
            accession="0009999999-26-000010",
            source_url="https://example.invalid/synthetic_10q.html",
            raw=mutated,
            published_at=PUBLISHED,
        )
    assert excinfo.value.existing_content_hash == original_hash


def test_canonical_text_is_persisted_and_spans_reverify(
    corpus_conn: psycopg.Connection,
) -> None:
    """Finding 5: the canonical parsed text is stored content-addressed and
    recorded on the version row; span offsets + text hashes re-verify
    against exactly the persisted text."""
    storage = MockStorageProvider()
    outcome = _ingest(corpus_conn, storage)
    row = corpus_conn.execute(
        "SELECT canonical_text_key FROM document_versions WHERE id = %s",
        (outcome.document_version_id,),
    ).fetchone()
    assert row is not None
    text_key = str(row[0])
    assert text_key.startswith("text/sha256/")
    persisted = storage.get(text_key).decode()
    # Content-addressed: the key commits to the stored bytes.
    assert hashlib.sha256(persisted.encode()).hexdigest() == text_key.rsplit("/", 1)[-1]
    spans = corpus_conn.execute(
        "SELECT start_char, end_char, text_hash FROM source_spans"
        " WHERE document_version_id = %s",
        (outcome.document_version_id,),
    ).fetchall()
    assert len(spans) == outcome.spans > 0
    for start_char, end_char, span_hash in spans:
        covered = persisted[start_char:end_char]
        assert span_hash == "sha256:" + hashlib.sha256(covered.encode()).hexdigest()


def test_concurrent_identical_jobs_converge_without_unique_violation(
    corpus_conn: psycopg.Connection,
) -> None:
    """Finding 10: two racing identical jobs on separate connections —
    exactly one does the work, the other blocks on the up-front ledger claim
    and replays the recorded result. No UniqueViolation escapes."""
    url = os.environ["TEST_DATABASE_URL"]
    barrier = threading.Barrier(2, timeout=10)
    outcomes: list[object] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                barrier.wait()
                outcomes.append(_ingest(conn, MockStorageProvider()))
        except BaseException as exc:  # noqa: BLE001 — recorded for assertion
            failures.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not failures, f"no exception may escape the idempotency path: {failures!r}"
    statuses = sorted(outcome.status for outcome in outcomes)  # type: ignore[attr-defined]
    assert statuses == ["noop", "succeeded"], "exactly one worker does the work"
    keys = {outcome.job_key for outcome in outcomes}  # type: ignore[attr-defined]
    versions = {outcome.document_version_id for outcome in outcomes}  # type: ignore[attr-defined]
    assert len(keys) == 1 and len(versions) == 1, "both converge on one result"
    counts = _counts(corpus_conn)
    assert counts["ingestion_runs"] == 1
    assert counts["document_versions"] == 1
    run_status = corpus_conn.execute("SELECT status FROM ingestion_runs").fetchone()
    assert run_status is not None and run_status[0] == "succeeded"


def test_publish_race_surfaces_domain_error_not_db_error(
    corpus_conn: psycopg.Connection,
) -> None:
    """Finding 11: a publisher that loses the single-active race gets
    PublishConflictError (documented domain error), and its transaction
    rolls back cleanly — the competing version stays active."""
    outcome = _ingest(corpus_conn, MockStorageProvider())
    assert outcome.document_version_id is not None
    draft = create_corpus_version(
        corpus_conn, label="loser", document_version_ids=[outcome.document_version_id]
    )
    url = os.environ["TEST_DATABASE_URL"]
    competitor = str(uuid.uuid4())
    conflicts: list[PublishConflictError] = []
    failures: list[BaseException] = []

    def publish() -> None:
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                publish_corpus_version(conn, draft)
        except PublishConflictError as exc:
            conflicts.append(exc)
        except BaseException as exc:  # noqa: BLE001 — recorded for assertion
            failures.append(exc)

    with psycopg.connect(url) as blocker:
        # Pre-activate a competing version in an open transaction: the
        # publisher's promote step will block on the partial unique index.
        blocker.execute(
            "INSERT INTO corpus_versions (id, label, status, is_active)"
            " VALUES (%s, 'competitor', 'active', true)",
            (competitor,),
        )
        thread = threading.Thread(target=publish)
        thread.start()
        # Wait until the publisher is actually blocked on the index before
        # committing the competitor, so the ordering is deterministic.
        for _ in range(500):
            waiting = corpus_conn.execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE wait_event_type = 'Lock' AND state = 'active'"
            ).fetchone()
            if waiting is not None and int(waiting[0]) > 0:
                break
            thread.join(timeout=0.01)
            if not thread.is_alive():
                break
        blocker.commit()
        thread.join(timeout=30)
    assert not failures, f"raw database errors escaped the publish path: {failures!r}"
    assert len(conflicts) == 1, "the losing publisher must see PublishConflictError"
    assert "publish race" in str(conflicts[0])
    assert active_corpus_version(corpus_conn) == competitor
    draft_status = corpus_conn.execute(
        "SELECT status FROM corpus_versions WHERE id = %s", (draft,)
    ).fetchone()
    assert (
        draft_status is not None and draft_status[0] == "draft"
    ), "the losing publish must roll back completely"


def test_restatement_targets_latest_parsed_version_total_order(
    corpus_conn: psycopg.Connection,
) -> None:
    """Finding 12: with TWO parses of one prior document, restatement prior
    facts come from the LATEST parsed version only, with a total-order
    tiebreaker (created_at DESC, id DESC) when created_at ties."""
    storage = MockStorageProvider()
    first = _ingest(corpus_conn, storage)
    assert first.status == "succeeded"
    fact_row = corpus_conn.execute(
        "SELECT fact_key, value FROM financial_facts"
        " WHERE document_version_id = %s AND duplicate_of IS NULL"
        "   AND concept = 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'"
        "   AND dimensions = '{}'::jsonb",
        (first.document_version_id,),
    ).fetchone()
    assert fact_row is not None
    revenue_key, v1_value = str(fact_row[0]), str(fact_row[1])
    assert v1_value == "1250000000"

    def add_parse(version_id: str, parser_version: str, value: str, created_at: str) -> str:
        """A later re-parse of the SAME document with a corrected value."""
        section_id, span_id, fact_id = (str(uuid.uuid4()) for _ in range(3))
        corpus_conn.execute(
            "INSERT INTO document_versions (id, document_id, parser_version,"
            " normalizer_version, status, canonical_text_key, created_at)"
            " VALUES (%s, %s, %s, 'n2', 'parsed', 'text/sha256/re', %s)",
            (version_id, first.document_id, parser_version, created_at),
        )
        corpus_conn.execute(
            "INSERT INTO sections (id, document_version_id, heading, heading_path,"
            " ord, start_char, end_char) VALUES (%s, %s, 'Item 1', %s, 0, 0, 10)",
            (section_id, version_id, ["Item 1"]),
        )
        corpus_conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id,"
            " start_char, end_char, text_hash) VALUES (%s, %s, %s, 0, 5, %s)",
            (span_id, version_id, section_id, "sha256:" + "ab" * 32),
        )
        corpus_conn.execute(
            "INSERT INTO financial_facts (id, entity_id, document_version_id,"
            " concept, value, unit, period_type, period_start, period_end,"
            " source_span_id, fact_key)"
            " VALUES (%s, %s, %s,"
            " 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',"
            " %s, 'USD', 'duration', '2026-01-01', '2026-03-31', %s, %s)",
            (fact_id, ENTITY, version_id, value, span_id, revenue_key),
        )
        return fact_id

    # Two later re-parses sharing the SAME created_at: the total order must
    # break the tie on version id (DESC), deterministically.
    low_version = "00000000-0000-4000-8000-00000000000a"
    high_version = "00000000-0000-4000-8000-00000000000b"
    # Later than v1's now() default, identical for both re-parses (a tie).
    tie_created_at = "2027-01-01T00:00:00Z"
    add_parse(low_version, "fel-parser/2.0.0", "1255000000", tie_created_at)
    winning_fact = add_parse(high_version, "fel-parser/3.0.0", "1260000000", tie_created_at)

    prior = _prior_canonical_facts(
        corpus_conn,
        entity_id=ENTITY,
        published_before=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert prior[revenue_key].fact_id == winning_fact
    assert prior[revenue_key].value == "1260000000"
    # Reruns are stable (same total order, same target).
    again = _prior_canonical_facts(
        corpus_conn, entity_id=ENTITY, published_before=datetime(2026, 6, 1, tzinfo=UTC)
    )
    assert again[revenue_key].fact_id == winning_fact

    # A later filing restating revenue links to the latest parse's fact.
    amended = fixture_bytes("synthetic_10q.html").replace(b">1,250<", b">1,300<")
    outcome = _ingest(
        corpus_conn,
        storage,
        raw=amended,
        accession="0009999999-26-000012",
        published_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
    )
    assert outcome.status == "succeeded"
    restates = corpus_conn.execute(
        "SELECT DISTINCT restates FROM financial_facts"
        " WHERE document_version_id = %s AND restates IS NOT NULL",
        (outcome.document_version_id,),
    ).fetchall()
    assert [str(row[0]) for row in restates] == [winning_fact]


def test_executemany_batches_handle_documents_without_tables_or_facts(
    corpus_conn: psycopg.Connection,
) -> None:
    """Finding 15: the batched per-row inserts also work when a batch is
    empty (a filing with no tables and no inline facts)."""
    raw = b"<html><body><h1>Narrative only</h1><p>No numbers here.</p></body></html>"
    outcome = _ingest(corpus_conn, MockStorageProvider(), raw=raw)
    assert outcome.status == "succeeded"
    assert outcome.tables == 0
    assert outcome.facts == 0
    counts = _counts(corpus_conn)
    assert counts["document_versions"] == 1
    assert counts["sections"] == outcome.sections
    assert counts["tables_meta"] == 0
    assert counts["financial_facts"] == 0


def test_content_hash_single_format_everywhere(corpus_conn: psycopg.Connection) -> None:
    """Finding 16: bytes are hashed once and the 'sha256:<hex>' format is
    used consistently across parser output, documents, and the run ledger."""
    raw = fixture_bytes("synthetic_10q.html")
    content_hash, _ = content_address(raw)
    assert content_hash == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert parse_filing(raw).content_hash == content_hash
    outcome = _ingest(corpus_conn, MockStorageProvider(), raw=raw)
    document_hash = corpus_conn.execute(
        "SELECT content_hash FROM documents WHERE id = %s", (outcome.document_id,)
    ).fetchone()
    assert document_hash is not None and document_hash[0] == content_hash
    run_hash = corpus_conn.execute(
        "SELECT source_hash FROM ingestion_runs WHERE job_key = %s", (outcome.job_key,)
    ).fetchone()
    assert run_hash is not None and run_hash[0] == content_hash


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
