"""T0006: workspace lifecycle — idempotent create, ETag concurrency, audit."""

from __future__ import annotations

import uuid

import psycopg
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from tests.conftest import requires_db

pytestmark = requires_db


def _headers(org: tuple[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_mock_token(org[0], org[1], 'owner')}"}


def test_idempotent_create_and_etag_flow(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    key = f"ws-{uuid.uuid4()}"
    body = {
        "name": "Q3 revenue review",
        "entity_id": str(uuid.uuid4()),
        "base_currency": "USD",
        "fiscal_calendar": "FY-JAN31",
        "as_of": "2026-06-30T23:59:59Z",
    }
    headers = {**_headers(org_fixture), "Idempotency-Key": key}
    first = client.post("/v1/workspaces", headers=headers, json=body)
    assert first.status_code == 201
    replay = client.post("/v1/workspaces", headers=headers, json=body)
    assert replay.json()["id"] == first.json()["id"]

    workspace_id = first.json()["id"]
    assert first.headers["ETag"] == '"1"'

    stale = client.patch(
        f"/v1/workspaces/{workspace_id}",
        headers={**_headers(org_fixture), "If-Match": '"99"'},
        json={"name": "renamed"},
    )
    assert stale.status_code == 412

    good = client.patch(
        f"/v1/workspaces/{workspace_id}",
        headers={**_headers(org_fixture), "If-Match": '"1"'},
        json={"name": "renamed", "as_of": "2026-05-31T00:00:00Z"},
    )
    assert good.status_code == 200
    assert good.headers["ETag"] == '"2"'
    assert good.json()["as_of"].startswith("2026-05-31")

    with psycopg.connect(db_url) as conn:
        events = conn.execute(
            "SELECT action FROM audit_events WHERE object_id = %s ORDER BY id",
            (workspace_id,),
        ).fetchall()
    assert [e[0] for e in events] == ["workspace.created", "workspace.updated"]


def test_replay_carries_etag(client: TestClient, org_fixture: tuple[str, str]) -> None:
    """P2 regression: the idempotent replay must be byte-for-byte equivalent,
    including the ETag header."""
    key = f"etag-{uuid.uuid4()}"
    headers = {**_headers(org_fixture), "Idempotency-Key": key}
    body = {
        "name": "replay etag",
        "entity_id": str(uuid.uuid4()),
        "base_currency": "USD",
        "fiscal_calendar": "FY-JAN31",
        "as_of": "2026-06-30T00:00:00Z",
    }
    first = client.post("/v1/workspaces", headers=headers, json=body)
    replay = client.post("/v1/workspaces", headers=headers, json=body)
    assert replay.status_code == first.status_code == 201
    assert replay.headers.get("ETag") == first.headers.get("ETag") == '"1"'
    assert replay.json() == first.json()


def test_malformed_as_of_gets_contract_envelope(
    client: TestClient, org_fixture: tuple[str, str]
) -> None:
    """P1 regression: invalid timestamps are rejected at validation with the
    frozen error envelope, never a bare database 500."""
    response = client.post(
        "/v1/workspaces",
        headers={**_headers(org_fixture), "Idempotency-Key": f"bad-{uuid.uuid4()}"},
        json={
            "name": "bad time",
            "entity_id": str(uuid.uuid4()),
            "base_currency": "USD",
            "fiscal_calendar": "FY-JAN31",
            "as_of": "not-a-timestamp",
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["request_id"].startswith("req-")
    # Naive (timezone-less) datetimes are also rejected.
    naive = client.post(
        "/v1/workspaces",
        headers={**_headers(org_fixture), "Idempotency-Key": f"naive-{uuid.uuid4()}"},
        json={
            "name": "naive time",
            "entity_id": str(uuid.uuid4()),
            "base_currency": "USD",
            "fiscal_calendar": "FY-JAN31",
            "as_of": "2026-07-01T00:00:00",
        },
    )
    assert naive.status_code == 422
