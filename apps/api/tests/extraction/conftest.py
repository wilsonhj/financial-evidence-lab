"""Isolated extraction app and unique, durable PostgreSQL fixture rows."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import migrate
from app.auth import make_mock_token
from app.main import app as main_app


def ensure_extraction_api_database(base_url: str) -> str:
    """Provision this lane without touching the worker's ``_extraction`` sibling.

    The API commits immutable evidence/history, so it cannot share the base
    corpus database or the worker fixtures' potentially rebuilt sibling. Use
    the existing checksummed migration ledger instead of a first-table probe:
    pending migrations advance existing test data, while drift fails closed.
    Never drop a database or silently baseline an untracked schema.
    """
    connection = psycopg.conninfo.conninfo_to_dict(base_url)
    base_name = connection.get("dbname", "")
    database = base_name + "_extraction_api"
    if not base_name or len(database.encode("utf-8")) > 63:
        raise ValueError("TEST_DATABASE_URL needs an explicit, bounded database name")
    connection["dbname"] = database
    url = psycopg.conninfo.make_conninfo(**connection)
    with psycopg.connect(base_url, autocommit=True) as conn:
        try:
            conn.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(database))
            )
        except psycopg.errors.DuplicateDatabase:
            pass

    migrations = migrate.discover_migrations(Path(__file__).resolve().parents[4] / "db/migrations")
    with psycopg.connect(url, autocommit=True) as conn:
        migrate.acquire_lock(conn)
        try:
            migrate.ensure_ledger(conn)
            plan = migrate.build_plan(migrations, migrate.read_ledger(conn))
            if plan.drifted or plan.missing:
                raise RuntimeError("Extraction API test database migration ledger does not match")
            for migration in plan.pending:
                migrate.apply_migration(conn, migration)
        finally:
            migrate.release_lock(conn)
    return url


@pytest.fixture(scope="session")
def extraction_database_url() -> str:
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        if os.environ.get("FEL_REQUIRE_DB") == "1":
            raise RuntimeError("FEL_REQUIRE_DB=1 but TEST_DATABASE_URL is unset")
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_api_database(base)


@pytest.fixture
def extraction_client() -> TestClient:
    from app.extraction import router

    app = FastAPI(exception_handlers=main_app.exception_handlers)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def extraction_url(monkeypatch: pytest.MonkeyPatch, extraction_database_url: str) -> str:
    monkeypatch.setenv("FEL_DATABASE_URL", extraction_database_url)
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    return extraction_database_url


@pytest.fixture
def extraction_tenant(extraction_url: str) -> dict[str, Any]:
    ids = {key: str(uuid.uuid4()) for key in ("org", "user", "workspace", "entity", "policy")}
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO organizations(id,name) VALUES (%s,'Extraction test')", (ids["org"],)
        )
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'owner')",
            (ids["org"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of)"
            " VALUES (%s,%s,'Extraction',%s,'USD','FY','2026-06-30T00:00:00Z')",
            (ids["workspace"], ids["org"], ids["entity"]),
        )
        conn.execute(
            "INSERT INTO extraction_policies(id,org_id,version,created_by) VALUES (%s,%s,1,%s)",
            (ids["policy"], ids["org"], ids["user"]),
        )
    ids["headers"] = {
        "Authorization": f"Bearer {make_mock_token(ids['org'], ids['user'], 'owner')}"
    }
    return ids


@pytest.fixture
def seeded_runs(extraction_url: str, extraction_tenant: dict[str, Any]) -> list[str]:
    tenant = extraction_tenant
    corpus = str(uuid.uuid4())
    ids = sorted(str(uuid.uuid4()) for _ in range(5))
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO corpus_versions(id,label,status) VALUES (%s,'read fixture','superseded')",
            (corpus,),
        )
        for run_id in reversed(ids):
            conn.execute(
                "INSERT INTO extraction_runs(id,org_id,workspace_id,entity_id,modes,as_of,"
                "corpus_version_id,ontology_version,workflow_version,provider,model,policy_id,"
                "input_hash,idempotency_key,created_by,created_at) VALUES "
                "(%s,%s,%s,%s,ARRAY['kpi'],'2026-06-30Z',%s,'ontology/v1',"
                "'extraction-workflow/v3','mock','mock-structured-v1',%s,%s,%s,%s,'2026-01-01Z')",
                (
                    run_id,
                    tenant["org"],
                    tenant["workspace"],
                    tenant["entity"],
                    corpus,
                    tenant["policy"],
                    "sha256:" + "a" * 64,
                    run_id,
                    tenant["user"],
                ),
            )
    return ids


@pytest.fixture
def source_fixture(extraction_url, extraction_tenant, tmp_path, monkeypatch):
    tenant = extraction_tenant
    ids = {name: str(uuid.uuid4()) for name in ("document", "version", "section", "span", "corpus")}
    text = "Annual recurring revenue was $100 million at December 31, 2025."
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    storage_key = "canonical/" + ids["version"]
    path = tmp_path / storage_key
    path.parent.mkdir(parents=True)
    path.write_text(text)
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO documents(id,entity_id,accession,form,source_url,content_hash,storage_key,"
            "published_at,filed_at) VALUES (%s,%s,%s,'10-K','https://example.invalid/filing',%s,%s,"
            "'2026-02-01Z','2026-02-01Z')",
            (ids["document"], tenant["entity"], ids["document"], digest, storage_key),
        )
        conn.execute(
            "INSERT INTO document_versions(id,document_id,parser_version,normalizer_version,status,"
            "canonical_text_key) VALUES (%s,%s,'parser/v1','normalizer/v1','parsed',%s)",
            (ids["version"], ids["document"], storage_key),
        )
        conn.execute(
            "INSERT INTO sections(id,document_version_id,heading,heading_path,ord,"
            "start_char,end_char)"
            " VALUES (%s,%s,'Results',ARRAY['Results'],0,0,%s)",
            (ids["section"], ids["version"], len(text)),
        )
        conn.execute(
            "INSERT INTO source_spans(id,document_version_id,section_id,start_char,"
            "end_char,text_hash)"
            " VALUES (%s,%s,%s,0,%s,%s)",
            (ids["span"], ids["version"], ids["section"], len(text), digest),
        )
        conn.execute(
            "INSERT INTO corpus_versions(id,label,status) VALUES (%s,'Sources','superseded')",
            (ids["corpus"],),
        )
        conn.execute(
            "INSERT INTO corpus_version_documents(corpus_version_id,document_version_id) "
            "VALUES (%s,%s)",
            (ids["corpus"], ids["version"]),
        )
    return {**ids, "text": text, "hash": digest, "path": path}


@pytest.fixture
def waiting_review_fixture(extraction_client, extraction_tenant, extraction_url, source_fixture):
    from psycopg.rows import dict_row

    from fel_workers.extraction.handler import handle_extraction_run
    from tests.extraction.test_mock_lifecycle import ScopedMock
    from tests.extraction.test_run_creation import _create

    response = _create(extraction_client, extraction_tenant, source_fixture)
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with psycopg.connect(extraction_url, row_factory=dict_row) as conn:
        job = conn.execute("SELECT org_id,payload FROM jobs WHERE id=%s", (run_id,)).fetchone()
    with psycopg.connect(extraction_url, autocommit=True) as conn:
        conn.execute("SET ROLE fel_worker")
        state = handle_extraction_run(
            conn,
            ScopedMock(extraction_tenant, source_fixture),
            job["payload"],
            job_org_id=str(job["org_id"]),
        )
    assert state.status == "waiting_review"
    with psycopg.connect(extraction_url, row_factory=dict_row) as conn:
        proposal = conn.execute(
            "SELECT id,payload FROM extraction_proposals WHERE run_id=%s", (run_id,)
        ).fetchone()
    return {"run": run_id, "proposal": str(proposal["id"]), "payload": proposal["payload"]}
