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


def test_workspace_listing_keeps_new_workspaces_after_fifty(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO workspaces (id, org_id, name, entity_id, base_currency,"
            " fiscal_calendar, as_of) SELECT gen_random_uuid(), %s, 'workspace ' || n,"
            " gen_random_uuid(), 'USD', 'FY-JAN31', now() FROM generate_series(1, 51) n",
            (org_fixture[0],),
        )
    response = client.get("/v1/workspaces", headers=_headers(org_fixture), params={"limit": 200})
    assert response.status_code == 200
    assert len(response.json()) == 51


def test_workspace_pages_reach_all_history_and_legacy_fails_closed(client, org_fixture, db_url):
    ids = sorted(str(uuid.uuid4()) for _ in range(251))
    with psycopg.connect(db_url) as conn:
        for wid in reversed(ids):
            conn.execute(
                "INSERT INTO workspaces (id,org_id,name,entity_id,base_currency,"
                "fiscal_calendar,as_of,created_at) VALUES (%s,%s,'page',%s,'USD','FY',"
                "'2026-01-01Z','2026-01-01Z')",
                (wid, org_fixture[0], uuid.uuid4()),
            )
    url = "/v1/workspaces"
    response = client.get(url, headers=_headers(org_fixture))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAGINATION_REQUIRED"
    for order, expected in [("asc", ids), ("desc", list(reversed(ids)))]:
        seen = []
        cursor = None
        previous = None
        while True:
            params = {"limit": 50, "order": order}
            if cursor:
                params["cursor"] = cursor
            page = client.get(url, headers=_headers(org_fixture), params=params)
            assert page.status_code == 200, page.text
            assert page.headers["X-FEL-Page-Limit"] == "50"
            actual = [r["id"] for r in page.json()]
            assert len(actual) <= 50
            if previous:
                back = client.get(
                    url,
                    headers=_headers(org_fixture),
                    params={"cursor": page.headers["X-FEL-Previous-Cursor"]},
                )
                assert [r["id"] for r in back.json()] == previous
            seen.extend(actual)
            previous = actual
            cursor = page.headers.get("X-FEL-Next-Cursor")
            if not cursor:
                break
        assert seen == expected


def test_workspace_high_water_and_cross_tenant_cursor(client, org_fixture, db_url):
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, "
            "fiscal_calendar, as_of, created_at) SELECT gen_random_uuid(), %s, 'water', "
            "gen_random_uuid(), 'USD', 'FY', now(), '2020-01-01' FROM generate_series(1,"
            " 3)",
            (org_fixture[0],),
        )
    first = client.get("/v1/workspaces", params={"limit": 2}, headers=_headers(org_fixture))
    cursor = first.headers["X-FEL-Next-Cursor"]
    with psycopg.connect(db_url) as conn:
        added = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, "
            "fiscal_calendar, as_of, created_at) VALUES (%s, %s, 'append', %s, 'USD', "
            "'FY', now(), '2030-01-01')",
            (added, org_fixture[0], uuid.uuid4()),
        )
        other = str(uuid.uuid4())
        conn.execute("INSERT INTO organizations(id,name) VALUES (%s,%s)", (other, other))
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'owner')",
            (other, org_fixture[1]),
        )
    page = client.get("/v1/workspaces", params={"cursor": cursor}, headers=_headers(org_fixture))
    assert len(page.json()) == 1
    refresh = client.get(
        "/v1/workspaces", params={"limit": 2, "order": "desc"}, headers=_headers(org_fixture)
    )
    assert refresh.json()[0]["id"] == added
    swapped = client.get(
        "/v1/workspaces", params={"cursor": cursor}, headers=_headers((other, org_fixture[1]))
    )
    assert swapped.status_code == 422
    assert added not in swapped.text
    for params in [{"cursor": cursor, "limit": 1}, {"cursor": cursor, "order": "desc"}]:
        assert (
            client.get("/v1/workspaces", params=params, headers=_headers(org_fixture)).status_code
            == 422
        )
