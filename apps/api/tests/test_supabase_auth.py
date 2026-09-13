"""Offline authentication uses generated keys and an injected HTTP transport."""

from app.auth import MockTokenVerifier
from app.dependencies import get_verifier


def test_supabase_mode_selects_production_boundary(monkeypatch):
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    monkeypatch.setenv("FEL_AUTH_ISSUER", "https://identity.example/auth/v1")
    verifier = get_verifier()
    assert not isinstance(verifier, MockTokenVerifier)
