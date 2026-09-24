"""Capabilities are a current database projection, never bearer role claims."""

import uuid

import psycopg
import pytest


@pytest.mark.parametrize(
    ("role", "actions"),
    [
        ("owner", ["create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"]),
        ("editor", ["create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"]),
        ("reviewer", ["accept", "edit", "reject", "merge", "correct"]),
        ("viewer", []),
    ],
)
def test_current_role_overrides_forged_owner_claim(
    extraction_client, extraction_tenant, extraction_url, role, actions
):
    tenant = extraction_tenant
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "UPDATE memberships SET role=%s WHERE org_id=%s AND user_id=%s",
            (role, tenant["org"], tenant["user"]),
        )
    response = extraction_client.get(
        f"/v1/workspaces/{tenant['workspace']}/extraction-permissions", headers=tenant["headers"]
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"workspace_id": tenant["workspace"], "allowed_actions": actions}
    assert response.headers["Cache-Control"] == "no-store"


def test_workspace_visibility_and_authentication(extraction_client, extraction_tenant):
    tenant = extraction_tenant
    path = f"/v1/workspaces/{tenant['workspace']}/extraction-permissions"
    assert extraction_client.get(path).status_code == 401
    assert (
        extraction_client.get(
            f"/v1/workspaces/{uuid.uuid4()}/extraction-permissions", headers=tenant["headers"]
        ).status_code
        == 404
    )
