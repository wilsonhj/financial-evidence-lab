"""Real PostgreSQL membership remains authoritative after signature verification."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.dependencies import get_tenant_context
from app.supabase_auth import SupabaseTokenVerifier
from tests.conftest import requires_db

ISSUER = "https://identity.example/auth/v1"
pytestmark = requires_db


@pytest.fixture
def authenticated(monkeypatch):
    from app import dependencies

    private = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    payload = json.dumps({"keys": [{**public, "kid": "offline"}]}).encode()
    verifier = SupabaseTokenVerifier(
        ISSUER,
        "authenticated",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(payload)
            )
        ),
    )
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "public")
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    monkeypatch.setenv("FEL_AUTH_ISSUER", ISSUER)
    monkeypatch.setattr(dependencies, "_supabase_verifier", lambda *_: verifier)

    def bearer(org, user):
        now = int(datetime.now(UTC).timestamp())
        value = jwt.encode(
            {
                "iss": ISSUER,
                "aud": "authenticated",
                "sub": user,
                "iat": now,
                "exp": now + 600,
                "app_metadata": {"org_id": org},
                "role": "owner",
                "user_metadata": {"role": "owner", "org_id": str(uuid4())},
            },
            private,
            algorithm="ES256",
            headers={"kid": "offline"},
        )
        return "Bearer " + value

    return verifier, bearer


@pytest.mark.parametrize("role", ["owner", "editor", "reviewer", "viewer"])
def test_signed_candidate_gets_database_role(authenticated, db_url, org_fixture, role):
    verifier, bearer = authenticated
    org, user = org_fixture
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE memberships SET role=%s WHERE org_id=%s AND user_id=%s", (role, org, user)
        )
    header = bearer(org.upper(), user.upper())
    assert verifier.verify(header.removeprefix("Bearer ")).role == "viewer"
    current = get_tenant_context(header, verifier)
    assert (current.org_id, current.user_id, current.role) == (org, user, role)


def test_membership_removal_takes_effect_with_cached_signature(
    authenticated, client, db_url, org_fixture
):
    _, bearer = authenticated
    org, user = org_fixture
    headers = {"Authorization": bearer(org, user)}
    assert client.get("/v1/workspaces", headers=headers).status_code == 200
    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM memberships WHERE org_id=%s AND user_id=%s", (org, user))
    response = client.get("/v1/workspaces", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_MEMBER"


def test_verified_claims_do_not_cross_tenants_or_escalate_viewer(
    authenticated, client, db_url, org_fixture
):
    _, bearer = authenticated
    org, user = org_fixture
    other_org, workspace = str(uuid4()), str(uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute("INSERT INTO organizations(id,name) VALUES (%s,'Other')", (other_org,))
        conn.execute(
            "INSERT INTO workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of) "
            "VALUES (%s,%s,'Other workspace',%s,'USD','FY','2026-01-01Z')",
            (workspace, other_org, str(uuid4())),
        )
        conn.execute(
            "UPDATE memberships SET role='viewer' WHERE org_id=%s AND user_id=%s", (org, user)
        )
    headers = {"Authorization": bearer(org, user)}
    hidden = client.get("/v1/workspaces/" + workspace, headers=headers)
    absent = client.get("/v1/workspaces/" + str(uuid4()), headers=headers)
    assert hidden.status_code == absent.status_code == 404
    denied = client.post(
        "/v1/workspaces",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "name": "Forbidden",
            "entity_id": str(uuid4()),
            "base_currency": "USD",
            "fiscal_calendar": "FY",
            "as_of": "2026-01-01T00:00:00Z",
        },
    )
    assert denied.status_code == 403
    nonmember = client.get("/v1/workspaces", headers={"Authorization": bearer(other_org, user)})
    assert nonmember.status_code == 403
