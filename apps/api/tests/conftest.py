"""Shared fixtures. DB-backed tests need TEST_DATABASE_URL pointing at a
disposable Postgres with db/migrations applied; they skip otherwise."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)


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
