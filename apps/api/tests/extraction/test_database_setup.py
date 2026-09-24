"""Extraction API tests provision their own durable, current-schema database."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest

import migrate
from tests.extraction.conftest import ensure_extraction_api_database


def test_database_setup_applies_current_migrations_and_preserves_rows(extraction_url: str) -> None:
    base = os.environ["TEST_DATABASE_URL"]
    base_name = psycopg.conninfo.conninfo_to_dict(base)["dbname"]
    org_id = str(uuid.uuid4())
    with psycopg.connect(extraction_url) as conn:
        assert conn.execute("SELECT current_database()").fetchone() == (
            base_name + "_extraction_api",
        )
        migrations = migrate.discover_migrations(
            Path(__file__).resolve().parents[4] / "db" / "migrations"
        )
        plan = migrate.build_plan(migrations, migrate.read_ledger(conn))
        assert plan.is_current and not plan.missing
        assert conn.execute(
            "SELECT to_regclass('public.approved_extraction_versions')"
        ).fetchone() == ("approved_extraction_versions",)
        conn.execute(
            "INSERT INTO organizations(id, name) VALUES (%s, 'API setup preservation')", (org_id,)
        )

    assert ensure_extraction_api_database(base) == extraction_url
    with psycopg.connect(extraction_url) as conn:
        assert conn.execute("SELECT id FROM organizations WHERE id=%s", (org_id,)).fetchone() == (
            uuid.UUID(org_id),
        )


@pytest.mark.parametrize("dbname", ["", "x" * 50])
def test_database_setup_rejects_ambiguous_or_truncated_name(dbname: str, monkeypatch) -> None:
    def unexpected_connect(*args, **kwargs):
        pytest.fail("invalid database identity must fail before connecting")

    monkeypatch.setattr(psycopg, "connect", unexpected_connect)
    with pytest.raises(ValueError, match="database name"):
        ensure_extraction_api_database(psycopg.conninfo.make_conninfo(dbname=dbname))
