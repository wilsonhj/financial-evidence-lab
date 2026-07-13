"""Shared fixtures for worker tests. DB-backed suites need TEST_DATABASE_URL
pointing at a disposable Postgres with db/migrations applied; they skip
otherwise (CI always provides one)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

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


@pytest.fixture()
def corpus_conn() -> Iterator[psycopg.Connection]:
    """Autocommit superuser connection with corpus + jobs tables emptied."""
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        for table in _CORPUS_TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list
        conn.execute("DELETE FROM jobs")
        yield conn
