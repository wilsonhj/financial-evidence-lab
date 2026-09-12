"""Isolated extraction app and unique, durable PostgreSQL fixture rows."""

from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from app.main import app as main_app


@pytest.fixture
def extraction_client() -> TestClient:
    from app.extraction import router

    app = FastAPI(exception_handlers=main_app.exception_handlers)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def extraction_url(monkeypatch: pytest.MonkeyPatch) -> str:
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL not configured")
    parsed = urlsplit(base)
    url = urlunsplit(parsed._replace(path=parsed.path + "_extraction"))
    monkeypatch.setenv("FEL_DATABASE_URL", url)
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    return url


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
