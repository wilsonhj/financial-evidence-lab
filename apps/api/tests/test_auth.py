"""Mock token verification and the authentication boundary (no DB needed)."""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.auth import MockTokenVerifier, TokenVerificationError, make_mock_token


def test_mock_token_round_trip() -> None:
    token = make_mock_token("11111111-1111-4111-8111-111111111111", "u-1", "editor")
    ctx = MockTokenVerifier().verify(token)
    assert ctx.role == "editor"
    assert ctx.org_id.startswith("11111111")


def test_bad_tokens_rejected() -> None:
    verifier = MockTokenVerifier()
    with pytest.raises(TokenVerificationError):
        verifier.verify("not-a-mock-token")
    with pytest.raises(TokenVerificationError):
        verifier.verify("mock.!!!!")


def test_endpoints_require_bearer(client: TestClient) -> None:
    response = client.get("/v1/workspaces")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert "request_id" in body["error"]


def test_error_envelope_on_validation(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers.get("X-Request-ID", "").startswith("req-")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        17,
        True,
        "private-token-text",
        {"org_id": None, "sub": "user", "role": "viewer"},
        {"org_id": {}, "sub": "user", "role": "viewer"},
        {"org_id": "org", "sub": [], "role": "viewer"},
        {"org_id": "", "sub": "user", "role": "viewer"},
        {"org_id": " ", "sub": "user", "role": "viewer"},
        {"org_id": "org", "sub": "", "role": "viewer"},
        {"org_id": "org", "sub": " ", "role": "viewer"},
        {"org_id": "org", "sub": "user", "role": ["owner"]},
    ],
)
def test_malformed_mock_claims_are_401_before_membership(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, payload
) -> None:
    from app import dependencies

    def must_not_resolve(_):
        pytest.fail("Malformed identity reached database membership resolution")

    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    monkeypatch.setattr(dependencies, "resolve_membership", must_not_resolve)
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    response = client.get("/v1/workspaces", headers={"Authorization": "Bearer mock." + raw})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert "private-token-text" not in response.text


def test_deeply_nested_mock_claims_are_401_before_membership(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import dependencies

    def must_not_resolve(_):
        pytest.fail("Malformed identity reached database membership resolution")

    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    monkeypatch.setattr(dependencies, "resolve_membership", must_not_resolve)
    raw = base64.urlsafe_b64encode(("[" * 1100 + "0" + "]" * 1100).encode()).decode()
    response = client.get("/v1/workspaces", headers={"Authorization": "Bearer mock." + raw})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
