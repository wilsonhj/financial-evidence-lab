"""FastAPI dependencies for authentication and tenancy.

Token claims are treated as a *candidate* identity only: the canonical role
comes from the memberships table, resolved under RLS with the candidate's
claims applied. A caller who is not a member of the claimed organization
gets no membership row (RLS yields nothing for forged/nonexistent orgs)
and is rejected; a forged role claim is overridden by the stored role.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.auth import (
    MockTokenVerifier,
    TenantContext,
    TokenVerificationError,
    TokenVerifier,
)
from app.config import settings
from app.db import tenant_connection
from app.errors import api_error


def get_verifier() -> TokenVerifier:
    mode = settings().auth_mode
    if mode == "mock":
        return MockTokenVerifier()
    # The Supabase JWKS verifier is integration-credentialed work; it plugs in
    # here behind the same protocol when FEL_AUTH_MODE=supabase ships.
    raise api_error(500, "AUTH_MODE_UNSUPPORTED", f"Unsupported auth mode: {mode}")


def resolve_membership(candidate: TenantContext) -> TenantContext:
    """Return the caller's context with the canonical role from PostgreSQL."""
    with tenant_connection(candidate) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role FROM memberships WHERE org_id = %s AND user_id = %s",
                (candidate.org_id, candidate.user_id),
            )
            row = cur.fetchone()
    if row is None:
        raise api_error(403, "NOT_A_MEMBER", "Caller is not a member of the claimed organization.")
    return TenantContext(org_id=candidate.org_id, user_id=candidate.user_id, role=str(row["role"]))


def get_tenant_context(
    authorization: Annotated[str | None, Header()] = None,
    verifier: TokenVerifier = Depends(get_verifier),  # noqa: B008
) -> TenantContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise api_error(401, "UNAUTHENTICATED", "Missing bearer token.")
    try:
        candidate = verifier.verify(authorization.removeprefix("Bearer "))
    except TokenVerificationError as exc:
        raise api_error(401, "UNAUTHENTICATED", str(exc)) from exc
    return resolve_membership(candidate)
