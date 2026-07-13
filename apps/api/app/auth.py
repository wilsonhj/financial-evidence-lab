"""Authentication boundary.

TokenVerifier is the frozen seam: the mock verifier decodes unsigned
development tokens; the Supabase implementation (JWKS signature checks
against SUPABASE_URL) is integration-credentialed work and plugs in behind
the same protocol without touching callers. Membership/role is checked
against the memberships table, never trusted from the claim alone, and
user_metadata is never consulted.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TenantContext:
    """Contract tenant-context/v1."""

    org_id: str
    user_id: str
    role: str


ROLES = ("owner", "editor", "reviewer", "viewer")


class TokenVerificationError(Exception):
    pass


class TokenVerifier(Protocol):
    def verify(self, token: str) -> TenantContext: ...


class MockTokenVerifier:
    """Decodes `mock.<base64url(json)>` development tokens. No cryptography —
    usable only in FEL_AUTH_MODE=mock, which is the only mode M0 ships."""

    def verify(self, token: str) -> TenantContext:
        if not token.startswith("mock."):
            raise TokenVerificationError("unsupported token format")
        try:
            payload = json.loads(base64.urlsafe_b64decode(token[5:] + "=="))
        except (ValueError, binascii.Error) as exc:
            raise TokenVerificationError("undecodable token") from exc
        try:
            org_id, user_id, role = payload["org_id"], payload["sub"], payload["role"]
        except KeyError as exc:
            raise TokenVerificationError(f"missing claim: {exc}") from exc
        if role not in ROLES:
            raise TokenVerificationError("unknown role")
        return TenantContext(org_id=org_id, user_id=user_id, role=role)


def make_mock_token(org_id: str, user_id: str, role: str) -> str:
    raw = json.dumps({"org_id": org_id, "sub": user_id, "role": role}).encode()
    return "mock." + base64.urlsafe_b64encode(raw).decode().rstrip("=")
