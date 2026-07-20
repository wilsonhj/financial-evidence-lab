"""Shared fixtures. DB-backed tests need TEST_DATABASE_URL pointing at a
disposable Postgres with db/migrations applied; they skip otherwise."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)


def ensure_retrieval_database(base_url: str) -> str:
    """Create and migrate a dedicated ``<db>_retrieval`` sibling; return its URL.

    Retrieval integration tests commit into delete-immutable shared tables
    guarded by BEFORE DELETE triggers and an FK to ``corpus_versions``. Running
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


@pytest.fixture()
def db_url(monkeypatch: pytest.MonkeyPatch) -> str:
    assert TEST_DATABASE_URL is not None
    monkeypatch.setenv("FEL_DATABASE_URL", TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture()
def org_fixture(db_url: str) -> tuple[str, str]:
    """A fresh organization + owner membership, created as the superuser."""
    org_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, %s)", (org_id, f"org-{org_id[:8]}")
        )
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (org_id, user_id),
        )
    return org_id, user_id


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)
