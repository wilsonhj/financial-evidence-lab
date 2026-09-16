"""Deployment mode proofs before authentication or membership access."""

import pytest
from fastapi import HTTPException

from app import dependencies
from app.config import Settings
from app.deployment import require_auth_deployment


@pytest.mark.parametrize("mode", [None, "public", "fixture", "", " public", "public ", "unknown"])
def test_mock_rejected_without_synthetic_proof(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("FEL_DEPLOYMENT_MODE", raising=False)
    else:
        monkeypatch.setenv("FEL_DEPLOYMENT_MODE", mode)
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    with pytest.raises(HTTPException) as error:
        dependencies.get_verifier()
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "AUTH_UNAVAILABLE"


def test_public_supabase_preserved(monkeypatch):
    monkeypatch.delenv("FEL_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    sentinel = object()
    monkeypatch.setattr(dependencies, "_supabase_verifier", lambda *_: sentinel)
    assert dependencies.get_verifier() is sentinel


@pytest.fixture
def proof(monkeypatch, tmp_path):
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "synthetic-http")
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    monkeypatch.setenv("FEL_SYNTHETIC_HTTP_TARGET", "unit-target")
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://user@localhost/test")
    marker = tmp_path / ".synthetic-http-target"
    marker.write_bytes(b"unit-target")
    return marker


def test_synthetic_proof(proof):
    require_auth_deployment(Settings())


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "dbname=test",
        "host=/tmp dbname=test",
        "host=remote dbname=test",
        "host=localhost,remote dbname=test",
        "host=localhost hostaddr=192.0.2.1 dbname=test",
        "hostaddr=127.0.0.1 dbname=test",
        "postgresql://localhost,remote/test",
        "not a dsn",
        "host=localhost service=production dbname=test",
    ],
)
def test_synthetic_bad_dsn(proof, monkeypatch, dsn):
    monkeypatch.setenv("FEL_DATABASE_URL", dsn)
    with pytest.raises(HTTPException) as error:
        dependencies.get_verifier()
    assert error.value.status_code == 503


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_synthetic_loopback_hosts(proof, monkeypatch, host):
    monkeypatch.setenv("FEL_DATABASE_URL", f"host={host} dbname=test")
    require_auth_deployment(Settings())


@pytest.mark.parametrize("value", [b"other", b"unit-target\n", b"x" * 81, b"\xff", b""])
def test_marker_mismatch(proof, value):
    proof.write_bytes(value)
    with pytest.raises(HTTPException):
        dependencies.get_verifier()


def test_missing_marker(proof):
    proof.unlink()
    with pytest.raises(HTTPException):
        dependencies.get_verifier()


@pytest.mark.parametrize("value", ["1 ", "true", "", "0"])
def test_mock_optin_exact(proof, monkeypatch, value):
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", value)
    with pytest.raises(HTTPException):
        dependencies.get_verifier()


@pytest.mark.parametrize("target", ["ab", "x" * 81, "bad target", "valid\n", ""])
def test_target_syntax(proof, monkeypatch, target):
    monkeypatch.setenv("FEL_SYNTHETIC_HTTP_TARGET", target)
    with pytest.raises(HTTPException):
        dependencies.get_verifier()


def test_reader_hosted_proof(monkeypatch, tmp_path):
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "reader-smoke")
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")
    monkeypatch.setenv("FEL_READER_SMOKE_TARGET", "hosted-reader")
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://remote.example/db")
    (tmp_path / ".reader-smoke-target").write_bytes(b"hosted-reader")
    require_auth_deployment(Settings())
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    with pytest.raises(HTTPException):
        dependencies.get_verifier()


def test_public_rejected_before_verifier_and_membership(client, monkeypatch):
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "public")
    monkeypatch.setenv("FEL_AUTH_MODE", "mock")

    def forbidden(*args):
        pytest.fail("Rejected deployment reached identity or database")

    monkeypatch.setattr(dependencies, "MockTokenVerifier", forbidden)
    monkeypatch.setattr(dependencies, "resolve_membership", forbidden)
    response = client.get("/v1/workspaces", headers={"Authorization": "Bearer private-marker"})
    assert response.status_code == 503
    assert "private-marker" not in response.text
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE"])
def test_synthetic_rejects_libpq_environment_routing(proof, monkeypatch, name):
    monkeypatch.setenv(name, "private-config")
    with pytest.raises(HTTPException) as caught:
        dependencies.get_verifier()
    assert caught.value.status_code == 503
    assert "private-config" not in str(caught.value.detail)
    assert caught.value.__context__ is None


def test_proof_error_has_no_sensitive_exception_context(proof, monkeypatch):
    monkeypatch.setenv("FEL_DATABASE_URL", "private-config")
    with pytest.raises(HTTPException) as caught:
        dependencies.get_verifier()
    assert caught.value.__context__ is None
    assert "private-config" not in str(caught.value.detail)


def test_maximum_target_and_exact_marker(proof, monkeypatch):
    target = "a" * 80
    monkeypatch.setenv("FEL_SYNTHETIC_HTTP_TARGET", target)
    proof.write_bytes(target.encode())
    require_auth_deployment(Settings())
    proof.write_bytes(target.encode() + b"x")
    with pytest.raises(HTTPException):
        dependencies.get_verifier()


def test_marker_directory_fails_safely(proof):
    proof.unlink()
    proof.mkdir()
    with pytest.raises(HTTPException) as caught:
        dependencies.get_verifier()
    assert caught.value.__context__ is None
    assert str(proof) not in str(caught.value.detail)


@pytest.mark.parametrize("auth", ["mock", "unknown", " supabase", "supabase ", ""])
def test_public_only_exact_supabase(monkeypatch, auth):
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "public")
    monkeypatch.setenv("FEL_AUTH_MODE", auth)
    with pytest.raises(HTTPException):
        dependencies.get_verifier()
