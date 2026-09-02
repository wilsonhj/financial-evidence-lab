"""Shared fixtures for worker tests. DB-backed suites need TEST_DATABASE_URL
pointing at a disposable Postgres with db/migrations applied; they skip
otherwise (CI always provides one)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from fel_workers.storage import apply_worker_db_role

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# FK-safe deletion order for a clean corpus slate between tests.
_CORPUS_TABLES = (
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
)


def ensure_organization(org_id: str, *, name: str = "test org") -> str:
    """Create the ``organizations`` row a tenant-scoped job now requires.

    Migration 0009 gave ``jobs.org_id`` a real foreign key, so a test that
    enqueues work for an invented tenant must first make that tenant exist.
    It runs on its OWN superuser connection because the fixture connections
    may already have adopted ``fel_worker`` (which cannot, by design, create
    organizations).
    """
    assert TEST_DATABASE_URL is not None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, %s)" " ON CONFLICT (id) DO NOTHING",
            (org_id, name),
        )
    return org_id


@pytest.fixture()
def corpus_conn() -> Iterator[psycopg.Connection]:
    """Autocommit connection with corpus + jobs tables emptied.

    Cleanup runs as the superuser (fel_worker has no DELETE by design, #190);
    the role switch is applied only AFTER the slate is clean, so with
    ``FEL_WORKER_DB_ROLE=fel_worker`` in the environment the whole worker
    suite exercises the ingestion/queue paths under the least-privilege job
    role instead of the owner. Unset, the fixture behaves exactly as before.
    """
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        for table in _CORPUS_TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list
        conn.execute("DELETE FROM jobs")
        apply_worker_db_role(conn)
        yield conn
