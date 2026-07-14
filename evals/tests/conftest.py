"""Shared fixtures for eval-harness tests. DB-backed suites need
TEST_DATABASE_URL pointing at a disposable Postgres with db/migrations
applied; they skip otherwise (CI always provides one)."""

from __future__ import annotations

import os

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# FK-safe deletion order for a clean corpus + queue slate between tests.
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


@pytest.fixture()
def qa_database_url() -> str:
    """URL of a disposable database whose corpus/queue tables were emptied."""
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        for table in _TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list
    return TEST_DATABASE_URL
