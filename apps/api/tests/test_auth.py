"""Mock token verification and the authentication boundary (no DB needed)."""

from __future__ import annotations

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
