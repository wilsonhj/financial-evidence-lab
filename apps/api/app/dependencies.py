"""FastAPI dependencies for authentication and tenancy."""

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
from app.errors import api_error


def get_verifier() -> TokenVerifier:
    mode = settings().auth_mode
    if mode == "mock":
        return MockTokenVerifier()
    # The Supabase JWKS verifier is integration-credentialed work; it plugs in
    # here behind the same protocol when FEL_AUTH_MODE=supabase ships.
    raise api_error(500, "AUTH_MODE_UNSUPPORTED", f"Unsupported auth mode: {mode}")


def get_tenant_context(
    authorization: Annotated[str | None, Header()] = None,
    verifier: TokenVerifier = Depends(get_verifier),  # noqa: B008
) -> TenantContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise api_error(401, "UNAUTHENTICATED", "Missing bearer token.")
    try:
        return verifier.verify(authorization.removeprefix("Bearer "))
    except TokenVerificationError as exc:
        raise api_error(401, "UNAUTHENTICATED", str(exc)) from exc
