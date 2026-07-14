"""T0111 (c): idempotency suite — a property-style rerun matrix over the
real ingestion pipeline against a real Postgres.

Beyond the per-feature regression tests on main (test_ingestion_pipeline),
this suite runs the SAME properties systematically across the whole
committed synthetic fixture library and a matrix of perturbations:

- same bytes / same accession / same versions  -> noop, zero writes,
  byte-identical corpus state (repeated N times);
- same bytes / different accession             -> a distinct document and
  version (never aliased onto the first);
- changed bytes / same accession               -> fail-closed DIVERGENT
  quarantine; original bytes, hash, and version rows untouched;
- parser or normalizer version bump            -> a NEW derived document
  version on the same document row; the old version is never mutated;
- rerun after a version bump                   -> noop per (bytes,
  accession, versions) tuple;
- N concurrent identical jobs                  -> exactly one worker does
  the work, all others replay the recorded result, no unique violation.
"""

from __future__ import annotations

import itertools
import os
import pathlib
import threading
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

import fel_workers.ingestion.pipeline as pipeline
from fel_providers.mocks import MockStorageProvider
from fel_workers.ingestion.pipeline import ingest_filing, job_key

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)

PUBLISHED = datetime(2027, 5, 5, 16, 30, tzinfo=UTC)

# The whole committed parseable synthetic fixture library.
PARSEABLE_FIXTURES = (
    "synthetic_10q.html",
    "synthetic_10q_stress.html",
    "synthetic_8k_narrative.html",
)

_SNAPSHOT_TABLES = (
    "documents",
    "document_versions",
    "sections",
    "source_spans",
    "tables_meta",
    "financial_facts",
    "ingestion_runs",
    "ingestion_quarantine",
)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _snapshot(conn: psycopg.Connection) -> dict[str, list[tuple]]:
    """Full ordered row snapshot: reruns must be byte-identical no-ops,
    not merely count-identical."""
    out: dict[str, list[tuple]] = {}
    for table in _SNAPSHOT_TABLES:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY 1"  # noqa: S608 — fixed table list
        ).fetchall()
        out[table] = rows
    return out


def _ingest(conn: psycopg.Connection, storage: MockStorageProvider, **overrides):
    params = {
        "entity_id": overrides.pop("entity_id", str(uuid.uuid4())),
        "accession": "0009999998-27-000010",
        "source_url": "https://example.invalid/synthetic.html",
        "raw": fixture_bytes("synthetic_10q_stress.html"),
        "published_at": PUBLISHED,
        "form": "10-Q",
    }
    params.update(overrides)
    return ingest_filing(conn, storage, **params)


@requires_db
@pytest.mark.parametrize("fixture_name", PARSEABLE_FIXTURES)
def test_same_bytes_same_accession_rerun_is_always_a_noop(
    corpus_conn: psycopg.Connection, fixture_name: str
) -> None:
    """Property: for EVERY fixture, an identical job rerun (three times)
    changes nothing — not a single row differs anywhere in the corpus."""
    storage = MockStorageProvider()
    entity = str(uuid.uuid4())
    first = _ingest(corpus_conn, storage, entity_id=entity, raw=fixture_bytes(fixture_name))
    assert first.status == "succeeded"
    frozen = _snapshot(corpus_conn)
    for _ in range(3):
        rerun = _ingest(corpus_conn, storage, entity_id=entity, raw=fixture_bytes(fixture_name))
        assert rerun.status == "noop"
        assert rerun.job_key == first.job_key
        assert rerun.document_id == first.document_id
        assert rerun.document_version_id == first.document_version_id
        assert (rerun.sections, rerun.spans, rerun.tables, rerun.facts) == (
            first.sections,
            first.spans,
            first.tables,
            first.facts,
        )
        assert _snapshot(corpus_conn) == frozen, "a rerun must write nothing"


@requires_db
@pytest.mark.parametrize("fixture_name", PARSEABLE_FIXTURES)
def test_same_bytes_under_other_accession_is_a_distinct_document(
    corpus_conn: psycopg.Connection, fixture_name: str
) -> None:
    storage = MockStorageProvider()
    entity = str(uuid.uuid4())
    raw = fixture_bytes(fixture_name)
    first = _ingest(corpus_conn, storage, entity_id=entity, raw=raw)
    second = _ingest(
        corpus_conn,
        storage,
        entity_id=entity,
        raw=raw,
        accession="0009999998-27-000011",
        published_at=datetime(2027, 6, 1, 9, 0, tzinfo=UTC),
    )
    assert first.status == second.status == "succeeded"
    assert second.job_key != first.job_key
    assert second.document_id != first.document_id
    assert second.document_version_id != first.document_version_id
    counts = {
        table: len(rows)
        for table, rows in _snapshot(corpus_conn).items()
        if table in ("documents", "document_versions", "ingestion_runs")
    }
    assert counts == {"documents": 2, "document_versions": 2, "ingestion_runs": 2}
    # Content-addressed raw storage still holds exactly one blob.
    hashes = corpus_conn.execute("SELECT DISTINCT content_hash FROM documents").fetchall()
    assert len(hashes) == 1


@requires_db
@pytest.mark.parametrize("fixture_name", PARSEABLE_FIXTURES)
def test_changed_bytes_same_accession_quarantines_divergent(
    corpus_conn: psycopg.Connection, fixture_name: str
) -> None:
    """Property: for EVERY fixture, a re-fetch with different bytes fails
    closed into DIVERGENT_ACCESSION_CONTENT and mutates nothing."""
    storage = MockStorageProvider()
    entity = str(uuid.uuid4())
    raw = fixture_bytes(fixture_name)
    first = _ingest(corpus_conn, storage, entity_id=entity, raw=raw)
    assert first.status == "succeeded"
    frozen = {
        table: rows
        for table, rows in _snapshot(corpus_conn).items()
        if table not in ("ingestion_runs", "ingestion_quarantine")
    }
    mutated = raw + b"<!-- divergent -->"
    outcome = _ingest(corpus_conn, storage, entity_id=entity, raw=mutated)
    assert outcome.status == "quarantined"
    assert outcome.reason_code == "DIVERGENT_ACCESSION_CONTENT"
    assert outcome.document_id == first.document_id
    assert outcome.document_version_id is None
    after = {
        table: rows
        for table, rows in _snapshot(corpus_conn).items()
        if table not in ("ingestion_runs", "ingestion_quarantine")
    }
    assert after == frozen, "divergent bytes must not touch published evidence"
    quarantine = corpus_conn.execute(
        "SELECT reason_code, accession FROM ingestion_quarantine"
    ).fetchall()
    assert quarantine == [("DIVERGENT_ACCESSION_CONTENT", "0009999998-27-000010")]
    # Rerunning the identical divergent job replays the quarantine result.
    rerun = _ingest(corpus_conn, storage, entity_id=entity, raw=mutated)
    assert rerun.status == "noop"
    assert rerun.reason_code == "DIVERGENT_ACCESSION_CONTENT"
    count = corpus_conn.execute("SELECT count(*) FROM ingestion_quarantine").fetchone()
    assert count is not None and count[0] == 1


@requires_db
@pytest.mark.parametrize("bump", ["parser", "normalizer", "both"])
def test_version_bump_creates_new_version_rows_without_mutating_old(
    corpus_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, bump: str
) -> None:
    """Matrix over version-component bumps: same bytes + same accession +
    a bumped parser/normalizer version is a NEW job producing a NEW derived
    document version on the SAME document; the original version row and its
    children are byte-identical afterwards."""
    storage = MockStorageProvider()
    entity = str(uuid.uuid4())
    first = _ingest(corpus_conn, storage, entity_id=entity)
    assert first.status == "succeeded"
    original_versions = corpus_conn.execute(
        "SELECT * FROM document_versions ORDER BY id"
    ).fetchall()

    if bump in ("parser", "both"):
        monkeypatch.setattr(pipeline, "PARSER_VERSION", "fel-parser/999.0.0-t0111")
    if bump in ("normalizer", "both"):
        monkeypatch.setattr(pipeline, "NORMALIZER_VERSION", "fel-xbrl/999.0.0-t0111")

    second = _ingest(corpus_conn, storage, entity_id=entity)
    assert second.status == "succeeded", "a version bump is new work, not a noop"
    assert second.job_key != first.job_key
    assert second.document_id == first.document_id, "same evidence, same document"
    assert second.document_version_id != first.document_version_id

    documents = corpus_conn.execute("SELECT count(*) FROM documents").fetchone()
    assert documents is not None and documents[0] == 1
    versions = corpus_conn.execute(
        "SELECT id::text, parser_version, normalizer_version FROM document_versions"
        " ORDER BY created_at, id"
    ).fetchall()
    assert len(versions) == 2
    by_id = {row[0]: (row[1], row[2]) for row in versions}
    expected_parser = "fel-parser/999.0.0-t0111" if bump in ("parser", "both") else None
    expected_normalizer = "fel-xbrl/999.0.0-t0111" if bump in ("normalizer", "both") else None
    new_parser, new_normalizer = by_id[str(second.document_version_id)]
    if expected_parser is not None:
        assert new_parser == expected_parser
    if expected_normalizer is not None:
        assert new_normalizer == expected_normalizer
    # The original version row is untouched.
    still_original = corpus_conn.execute(
        "SELECT * FROM document_versions WHERE id = %s",
        (first.document_version_id,),
    ).fetchall()
    assert [row for row in original_versions if row[0] == still_original[0][0]] == still_original

    # And the bumped job is itself idempotent on rerun.
    third = _ingest(corpus_conn, storage, entity_id=entity)
    assert third.status == "noop"
    assert third.document_version_id == second.document_version_id


@requires_db
def test_concurrent_identical_jobs_converge(corpus_conn: psycopg.Connection) -> None:
    """Four racing identical jobs on four connections: exactly one does the
    work, three replay it, one run-ledger row, one version, no exception."""
    url = os.environ["TEST_DATABASE_URL"]
    workers = 4
    barrier = threading.Barrier(workers, timeout=10)
    entity = str(uuid.uuid4())
    outcomes: list[object] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                barrier.wait()
                outcomes.append(_ingest(conn, MockStorageProvider(), entity_id=entity))
        except BaseException as exc:  # noqa: BLE001 — recorded for assertion
            failures.append(exc)

    threads = [threading.Thread(target=run) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not failures, f"no exception may escape the idempotency path: {failures!r}"
    statuses = sorted(outcome.status for outcome in outcomes)  # type: ignore[attr-defined]
    assert statuses == ["noop", "noop", "noop", "succeeded"]
    versions = {outcome.document_version_id for outcome in outcomes}  # type: ignore[attr-defined]
    assert len(versions) == 1
    runs = corpus_conn.execute("SELECT count(*), min(status) FROM ingestion_runs").fetchone()
    assert runs is not None and runs[0] == 1 and runs[1] == "succeeded"


def test_job_key_is_injective_over_every_component() -> None:
    """Pure property: two job-key tuples collide iff every component is
    equal — checked over the full cross-product of a two-value alphabet
    per component (2^5 = 32 tuples, all pairwise distinct unless equal)."""
    hashes = ("sha256:" + "0" * 64, "sha256:" + "1" * 64)
    parsers = ("p1", "p2")
    normalizers = ("n1", "n2")
    entities = ("e1", "e2")
    accessions = ("a1", "a2")
    tuples = list(itertools.product(hashes, parsers, normalizers, entities, accessions))
    keys = {job_key(h, p, n, entity_id=e, accession=a): (h, p, n, e, a) for h, p, n, e, a in tuples}
    assert len(keys) == len(tuples), "distinct job tuples must never share a key"
    for h, p, n, e, a in tuples:
        assert job_key(h, p, n, entity_id=e, accession=a) in keys
