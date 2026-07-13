"""T0005: row-level tenant isolation, including negative cross-tenant tests,
exercised through the real API against real RLS policies."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.auth import make_mock_token
from tests.conftest import requires_db

pytestmark = requires_db


def _headers(org_id: str, user_id: str, role: str = "owner") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_mock_token(org_id, user_id, role)}"}


def _create(client: TestClient, org: tuple[str, str]) -> str:
    org_id, user_id = org
    response = client.post(
        "/v1/workspaces",
        headers={**_headers(org_id, user_id), "Idempotency-Key": f"iso-{uuid.uuid4()}"},
        json={
            "name": "tenant test",
            "entity_id": str(uuid.uuid4()),
            "base_currency": "USD",
            "fiscal_calendar": "FY-JAN31",
            "as_of": "2026-07-01T00:00:00Z",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_cross_tenant_reads_are_empty(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    import psycopg

    workspace_id = _create(client, org_fixture)

    intruder_org, intruder_user = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, 'intruder')", (intruder_org,)
        )
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (intruder_org, intruder_user),
        )

    listing = client.get("/v1/workspaces", headers=_headers(intruder_org, intruder_user))
    assert listing.status_code == 200
    assert listing.json() == []

    lookup = client.get(
        f"/v1/workspaces/{workspace_id}", headers=_headers(intruder_org, intruder_user)
    )
    assert lookup.status_code == 404

    hijack = client.patch(
        f"/v1/workspaces/{workspace_id}",
        headers={**_headers(intruder_org, intruder_user), "If-Match": '"1"'},
        json={"name": "stolen"},
    )
    assert hijack.status_code == 404

    owner_view = client.get(f"/v1/workspaces/{workspace_id}", headers=_headers(*org_fixture))
    assert owner_view.status_code == 200
    assert owner_view.json()["name"] == "tenant test"


def test_viewer_cannot_mutate(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    import psycopg

    org_id, _ = org_fixture
    workspace_id = _create(client, org_fixture)
    viewer_user = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'viewer')",
            (org_id, viewer_user),
        )
    viewer = _headers(org_id, viewer_user, role="viewer")
    denied = client.patch(
        f"/v1/workspaces/{workspace_id}",
        headers={**viewer, "If-Match": '"1"'},
        json={"name": "nope"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_forged_org_or_nonmember_rejected(client: TestClient, org_fixture: tuple[str, str]) -> None:
    """P0 regression: claims are candidates, membership is canonical."""
    org_id, _ = org_fixture
    # Non-member user forging a real org id.
    nonmember = client.get("/v1/workspaces", headers=_headers(org_id, str(uuid.uuid4())))
    assert nonmember.status_code == 403
    assert nonmember.json()["error"]["code"] == "NOT_A_MEMBER"
    # Entirely fabricated org id.
    forged_org = client.get(
        "/v1/workspaces", headers=_headers(str(uuid.uuid4()), str(uuid.uuid4()))
    )
    assert forged_org.status_code == 403


def test_forged_role_claim_is_overridden_by_stored_role(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    """A viewer presenting an owner token still gets viewer permissions."""
    import psycopg

    org_id, _ = org_fixture
    viewer_user = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'viewer')",
            (org_id, viewer_user),
        )
    workspace_id = _create(client, org_fixture)
    forged_owner = _headers(org_id, viewer_user, role="owner")
    denied = client.patch(
        f"/v1/workspaces/{workspace_id}",
        headers={**forged_owner, "If-Match": '"1"'},
        json={"name": "escalated"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    create_denied = client.post(
        "/v1/workspaces",
        headers={**forged_owner, "Idempotency-Key": f"forge-{uuid.uuid4()}"},
        json={
            "name": "x",
            "entity_id": str(uuid.uuid4()),
            "base_currency": "USD",
            "fiscal_calendar": "FY-JAN31",
            "as_of": "2026-07-01T00:00:00Z",
        },
    )
    assert create_denied.status_code == 403
