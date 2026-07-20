"""Integration fixtures for retrieval index build/publish.

DB-backed tests need ``TEST_DATABASE_URL`` pointing at a disposable pgvector
Postgres with db/migrations applied; they skip cleanly otherwise. A local run
against the CI container looks like::

    TEST_DATABASE_URL=postgres://fel:fel-ci-only@localhost:55432/fel_test \\
        .venv/bin/python -m pytest packages/retrieval/tests -q

Retrieval index versions/items/embeddings are immutable (delete-forbidding
triggers), so the seed randomizes every id per test — reruns mint fresh rows
rather than colliding, and no teardown is possible or attempted.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

try:  # driver is a dev dependency; integration tests require it
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - psycopg is in requirements-dev
    psycopg = None  # type: ignore[assignment]

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def ensure_retrieval_database(base_url: str) -> str:
    """Create and migrate a dedicated ``<db>_retrieval`` sibling; return its URL.

    Retrieval integration tests commit into delete-immutable shared tables
    (``retrieval_index_versions``/``retrieval_items``/``retrieval_embeddings``,
    guarded by BEFORE DELETE triggers and an FK to ``corpus_versions``). Running
    them against the base ``TEST_DATABASE_URL`` permanently blocks the
    workers/ingestion suites' ``DELETE FROM corpus_versions`` cleanup, so they
    run against an isolated sibling database instead. Roles (``fel_app``) are
    cluster-level, so grants inside the migrations resolve there too.

    Idempotent: the database is created once (``DuplicateDatabase`` swallowed)
    and the non-idempotent migrations are applied only when the marker table is
    absent.
    """
    parsed = urlsplit(base_url)
    retrieval_db = parsed.path.lstrip("/") + "_retrieval"
    retrieval_url = urlunsplit(parsed._replace(path="/" + retrieval_db))

    with psycopg.connect(base_url, autocommit=True) as conn:
        try:
            conn.execute(f'CREATE DATABASE "{retrieval_db}"')  # noqa: S608 — derived name
        except psycopg.errors.DuplicateDatabase:
            pass

    repo_root = Path(__file__).resolve().parents[3]
    migrations = sorted(repo_root.glob("db/migrations/*.sql"))
    with psycopg.connect(retrieval_url, autocommit=True) as conn:
        marker = conn.execute("SELECT to_regclass('public.retrieval_index_versions')").fetchone()
        if marker is None or marker[0] is None:
            for path in migrations:
                conn.execute(path.read_text())
    return retrieval_url


_SENTENCES = [
    "Revenue was $100 million in fiscal 2025.",
    "Cost of sales was $40 million in fiscal 2025.",
    "Operating income reached $35 million for the year.",
    "Net income was $28 million, up from the prior year.",
    "Cash and equivalents totaled $52 million at year end.",
    "Total assets stood at $410 million as of December 31.",
]


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class SeededCorpus:
    corpus_version_id: str
    corpus: dict[str, Any]


def _seed_corpus(conn: Any) -> SeededCorpus:
    """Insert a small immutable corpus and return the matching builder view."""
    entity_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    document_version_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    fact_id = str(uuid.uuid4())
    corpus_version_id = str(uuid.uuid4())
    heading_path = ["ITEM 8", "FINANCIAL STATEMENTS"]

    canonical = "\n".join(_SENTENCES)
    spans: list[dict[str, Any]] = []
    offset = 0
    for sentence in _SENTENCES:
        start = offset
        end = start + len(sentence)
        spans.append(
            {
                "id": str(uuid.uuid4()),
                "section_id": section_id,
                "start_char": start,
                "end_char": end,
                "text": sentence,
                "text_hash": _sha(sentence),
                "heading_path": heading_path,
            }
        )
        offset = end + 1  # account for the "\n" separator

    conn.execute(
        "INSERT INTO documents (id, entity_id, accession, source_url, content_hash, "
        "storage_key, published_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
        (
            document_id,
            entity_id,
            f"acc-{uuid.uuid4()}",
            "https://example.test/doc",
            _sha(canonical),
            f"raw/{document_id}",
        ),
    )
    conn.execute(
        "INSERT INTO document_versions (id, document_id, parser_version, "
        "normalizer_version, canonical_text_key) VALUES (%s, %s, %s, %s, %s)",
        (document_version_id, document_id, "p/1", "n/1", f"text/sha256/{document_id}"),
    )
    conn.execute(
        "INSERT INTO sections (id, document_version_id, heading, heading_path, ord, "
        "start_char, end_char) VALUES (%s, %s, %s, %s, 0, 0, %s)",
        (section_id, document_version_id, "FINANCIAL STATEMENTS", heading_path, len(canonical)),
    )
    for span in spans:
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                span["id"],
                document_version_id,
                section_id,
                span["start_char"],
                span["end_char"],
                span["text_hash"],
            ),
        )
    conn.execute(
        "INSERT INTO financial_facts (id, entity_id, document_version_id, concept, value, "
        "unit, period_type, source_span_id, fact_key) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'duration', %s, %s)",
        (
            fact_id,
            entity_id,
            document_version_id,
            "Revenues",
            "100000000",
            "USD",
            spans[0]["id"],
            "revenues:FY2025:USD",
        ),
    )
    conn.execute(
        "INSERT INTO tables_meta (id, document_version_id, section_id, ord, headers, rows) "
        "VALUES (%s, %s, %s, 0, %s::jsonb, %s::jsonb)",
        (
            table_id,
            document_version_id,
            section_id,
            json.dumps(["metric", "value"]),
            json.dumps([{"source_span_id": spans[1]["id"]}, {"source_span_id": None}]),
        ),
    )
    conn.execute(
        "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'draft')",
        (corpus_version_id, f"corpus-{corpus_version_id[:8]}"),
    )
    conn.execute(
        "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id) "
        "VALUES (%s, %s)",
        (corpus_version_id, document_version_id),
    )

    corpus = {
        "entity_id": entity_id,
        "document_id": document_id,
        "document_version_id": document_version_id,
        "form": "10-K",
        "canonical_text": canonical,
        "source_spans": spans,
        "financial_facts": [{"id": fact_id, "source_span_id": spans[0]["id"], "period": "FY2025"}],
        "tables": [
            {
                "id": table_id,
                "section_id": section_id,
                "heading_path": heading_path,
                "rows": [
                    {"source_span_id": spans[1]["id"]},
                    {"source_span_id": None},
                ],
            }
        ],
    }
    return SeededCorpus(corpus_version_id=corpus_version_id, corpus=corpus)


@pytest.fixture(scope="session")
def retrieval_db_url() -> str:
    if TEST_DATABASE_URL is None or psycopg is None:
        pytest.skip("TEST_DATABASE_URL not configured (needs pgvector Postgres)")
    return ensure_retrieval_database(TEST_DATABASE_URL)


@pytest.fixture()
def pg_conn(retrieval_db_url: str) -> Iterator[Any]:
    with psycopg.connect(retrieval_db_url, autocommit=True) as conn:
        yield conn


@pytest.fixture()
def seed_corpus(pg_conn: Any) -> Callable[[], SeededCorpus]:
    """Factory: seed a fresh immutable corpus (call again for a second one)."""

    def factory() -> SeededCorpus:
        return _seed_corpus(pg_conn)

    return factory
