"""Offline authentication uses generated keys and an injected HTTP transport."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.auth import MockTokenVerifier, TokenVerificationError
from app.dependencies import get_verifier

ISSUER = "https://identity.example/auth/v1"
ORG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NOW = 1800000000


@pytest.fixture(autouse=True)
def frozen_tokens(monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(NOW, UTC)

    monkeypatch.setattr(jwt.api_jwt, "datetime", Frozen)


@pytest.fixture(scope="module", params=["ES256", "RS256"])
def signing(request):
    algorithm = request.param
    key = (
        ec.generate_private_key(ec.SECP256R1())
        if algorithm == "ES256"
        else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    implementation = jwt.algorithms.get_default_algorithms()[algorithm]
    public = json.loads(implementation.to_jwk(key.public_key()))
    return key, algorithm, {**public, "kid": "key-1", "use": "sig", "key_ops": ["verify"]}


def token(signing, *, claims=None, headers=None):
    key, algorithm, _ = signing
    payload = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": USER,
        "exp": NOW + 600,
        "iat": NOW,
        "app_metadata": {"org_id": ORG},
        "role": "service_role",
        "user_metadata": {"org_id": USER, "role": "owner"},
    }
    payload.update(claims or {})
    return jwt.encode(
        payload, key, algorithm=algorithm, headers={"kid": "key-1", **(headers or {})}
    )


def verifier(signing, *, handler=None):
    from app.supabase_auth import SupabaseTokenVerifier

    def stream_response(request):
        response = handler(request) if handler else httpx.Response(200, json={"keys": [signing[2]]})
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=httpx.ByteStream(response.content),
        )

    return SupabaseTokenVerifier(
        ISSUER,
        "authenticated",
        transport=httpx.MockTransport(stream_response),
    )


def test_supabase_mode_selects_production_boundary(monkeypatch):
    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "public")
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    monkeypatch.setenv("FEL_AUTH_ISSUER", "https://identity.example/auth/v1")
    verifier = get_verifier()
    assert not isinstance(verifier, MockTokenVerifier)


def test_signed_identity_canonicalizes_without_trusting_roles(signing):
    result = verifier(signing).verify(
        token(
            signing,
            claims={
                "sub": USER.upper(),
                "app_metadata": {"org_id": ORG.upper()},
                "org_id": USER,
            },
        )
    )
    assert (result.org_id, result.user_id, result.role) == (ORG, USER, "viewer")


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other.example/auth/v1"},
        {"aud": "other"},
        {"aud": ["authenticated"]},
        {"exp": NOW - 31},
        {"iat": NOW + 31},
        {"nbf": NOW + 31},
        {"exp": None},
        {"iat": None},
        {"sub": None},
        {"sub": "not-a-uuid"},
        {"sub": 123},
        {"app_metadata": None},
        {"app_metadata": {"org_id": "bad"}},
        {"app_metadata": {}, "org_id": ORG},
        {"exp": True},
        {"iat": "1800000000"},
        {"nbf": NOW + 0.5},
        {"exp": float("inf")},
        {"iat": float("nan")},
    ],
)
def test_claim_failures_are_safe(signing, claims):
    with pytest.raises(TokenVerificationError, match="Invalid access token"):
        verifier(signing).verify(token(signing, claims=claims))


def test_clock_skew_and_optional_not_before(signing):
    assert (
        verifier(signing)
        .verify(token(signing, claims={"exp": NOW - 29, "iat": NOW + 29, "nbf": NOW + 29}))
        .user_id
        == USER
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"kid": ""},
        {"kid": 1},
        {"kid": "x" * 129},
        {"crit": ["unknown"]},
        {"jku": "https://evil.example/keys"},
        {"jwk": {"kty": "oct"}},
        {"x5u": "https://evil.example/cert"},
        {"b64": False},
    ],
)
def test_untrusted_headers_never_fetch(signing, headers):
    def forbidden(_):
        pytest.fail("Invalid header reached key service")

    parts = token(signing).split(".")
    parts[0] = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "alg": signing[1],
                    "kid": "key-1",
                    **headers,
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    with pytest.raises(TokenVerificationError):
        verifier(signing, handler=forbidden).verify(".".join(parts))


def test_bad_signature_and_symmetric_algorithm(signing):
    signed = token(signing)
    parts = signed.split(".")
    parts[-1] = ("A" if parts[-1][0] != "A" else "B") + parts[-1][1:]
    with pytest.raises(TokenVerificationError):
        verifier(signing).verify(".".join(parts))
    symmetric = jwt.encode({"sub": USER}, "x" * 32, algorithm="HS256", headers={"kid": "key-1"})
    with pytest.raises(TokenVerificationError):
        verifier(signing).verify(symmetric)


@pytest.mark.parametrize("raw", ["", "mock.anything", "bad.token.data", "x" * 16385, "\ud800"])
def test_malformed_tokens_never_fetch(signing, raw):
    def forbidden(_):
        pytest.fail("Malformed token reached key service")

    with pytest.raises(TokenVerificationError):
        verifier(signing, handler=forbidden).verify(raw)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://evil.example"}),
        httpx.Response(500),
        httpx.Response(200, text="bad"),
        httpx.Response(200, content=b"x" * 65537, headers={"content-type": "application/json"}),
        httpx.Response(200, json={"keys": []}),
        httpx.Response(200, json={"keys": [None]}),
    ],
)
def test_unusable_key_service_fails_closed(signing, response):
    from app.auth import TokenVerifierUnavailable

    with pytest.raises(TokenVerifierUnavailable, match="Identity verification unavailable"):
        verifier(signing, handler=lambda _: response).verify(token(signing))


@pytest.mark.parametrize(
    "change",
    [
        {"d": "private"},
        {"k": "secret"},
        {"use": "enc"},
        {"key_ops": ["sign"]},
        {"alg": "HS256"},
        {"kid": ""},
        {"kty": "oct"},
    ],
)
def test_incompatible_key_metadata_fails_closed(signing, change):
    from app.auth import TokenVerifierUnavailable

    with pytest.raises(TokenVerifierUnavailable):
        verifier(
            signing,
            handler=lambda _: httpx.Response(200, json={"keys": [{**signing[2], **change}]}),
        ).verify(token(signing))


@pytest.mark.parametrize("count", [2, 33])
def test_duplicate_or_excessive_keys_rejected(signing, count):
    from app.auth import TokenVerifierUnavailable

    keys = (
        [signing[2]] * count
        if count == 2
        else [{**signing[2], "kid": f"key-{index + 1}"} for index in range(count)]
    )
    with pytest.raises(TokenVerifierUnavailable):
        verifier(signing, handler=lambda _: httpx.Response(200, json={"keys": keys})).verify(
            token(signing)
        )


def test_fixed_destination_and_cache_expiry_outage(signing, monkeypatch):
    from app import supabase_auth
    from app.auth import TokenVerifierUnavailable

    clock = [100.0]
    monkeypatch.setattr(supabase_auth, "monotonic", lambda: clock[0])
    calls = []

    def service(request):
        calls.append(str(request.url))
        assert request.headers.get("authorization") is None
        assert request.extensions["timeout"] == dict.fromkeys(
            ["connect", "read", "write", "pool"], 1.0
        )
        return (
            httpx.Response(200, json={"keys": [signing[2]]})
            if len(calls) == 1
            else httpx.Response(503)
        )

    subject = verifier(signing, handler=service)
    assert subject.verify(token(signing)).org_id == ORG
    clock[0] = 399.0
    assert subject.verify(token(signing)).org_id == ORG
    assert calls == [ISSUER + "/.well-known/jwks.json"]
    clock[0] = 400.0
    for _ in range(3):
        with pytest.raises(TokenVerifierUnavailable):
            subject.verify(token(signing))
    assert len(calls) == 2


def test_unknown_key_cooldown_rotation_and_failed_refresh(signing, monkeypatch):
    from app import supabase_auth
    from app.auth import TokenVerifierUnavailable

    clock = [100.0]
    monkeypatch.setattr(supabase_auth, "monotonic", lambda: clock[0])
    sets = [[signing[2]], [{**signing[2], "kid": "key-2"}]]
    calls = []

    def service(_):
        calls.append(1)
        return httpx.Response(200, json={"keys": sets.pop(0)}) if sets else httpx.Response(503)

    subject = verifier(signing, handler=service)
    subject.verify(token(signing))
    rotated = token(signing, headers={"kid": "key-2"})
    with pytest.raises(TokenVerificationError):
        subject.verify(rotated)
    assert len(calls) == 1
    clock[0] += 30
    assert subject.verify(rotated).user_id == USER
    clock[0] += 30
    with pytest.raises(TokenVerifierUnavailable):
        subject.verify(token(signing))
    assert subject.verify(rotated).user_id == USER
    with pytest.raises(TokenVerifierUnavailable):
        subject.verify(token(signing))
    assert len(calls) == 3


@pytest.mark.parametrize(
    "issuer",
    [
        "http://identity.example",
        ISSUER + "/",
        ISSUER + "?x=1",
        ISSUER + "?",
        ISSUER + "#x",
        ISSUER + "#",
        "https://user:secret@identity.example",
        "",
    ],
)
def test_bad_configuration_is_safe(monkeypatch, issuer):
    from fastapi import HTTPException

    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "public")
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    monkeypatch.setenv("FEL_AUTH_ISSUER", issuer)
    with pytest.raises(HTTPException) as error:
        get_verifier()
    assert error.value.status_code == 503
    assert "secret" not in str(error.value.detail)


def test_factory_initialization_is_shared_under_concurrent_requests(monkeypatch):
    from app import dependencies, supabase_auth

    dependencies._supabase_verifier.cache_clear()
    original = supabase_auth.SupabaseTokenVerifier
    entered, duplicate, release = Event(), Event(), Event()
    calls = []

    def construct(*args):
        calls.append(1)
        (entered if len(calls) == 1 else duplicate).set()
        assert release.wait(2)
        return original(*args)

    monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "public")
    monkeypatch.setenv("FEL_AUTH_MODE", "supabase")
    monkeypatch.setenv("FEL_AUTH_ISSUER", ISSUER)
    monkeypatch.setattr(supabase_auth, "SupabaseTokenVerifier", construct)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(get_verifier)
        assert entered.wait(1)
        second = pool.submit(get_verifier)
        try:
            assert not duplicate.wait(0.1)
        finally:
            release.set()
        assert first.result() is second.result()
    dependencies._supabase_verifier.cache_clear()


def test_concurrent_refresh_fetches_once_and_known_keys_do_not_wait(signing, monkeypatch):
    from app import supabase_auth

    clock = [100.0]
    monkeypatch.setattr(supabase_auth, "monotonic", lambda: clock[0])
    entered, release = Event(), Event()
    calls = []

    def service(_):
        calls.append(1)
        if len(calls) == 2:
            entered.set()
            assert release.wait(2)
        return httpx.Response(
            200,
            json={
                "keys": (
                    [signing[2], {**signing[2], "kid": "new"}] if len(calls) > 1 else [signing[2]]
                )
            },
        )

    subject = verifier(signing, handler=service)
    subject.verify(token(signing))
    clock[0] += 30
    rotated = token(signing, headers={"kid": "new"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(subject.verify, rotated)
        assert entered.wait(1)
        second = pool.submit(subject.verify, rotated)
        try:
            assert subject.verify(token(signing)).user_id == USER
        finally:
            release.set()
        assert first.result().user_id == second.result().user_id == USER
    assert len(calls) == 2


def test_incremental_deadline_closes_slow_response(signing, monkeypatch):
    from app import supabase_auth
    from app.auth import TokenVerifierUnavailable

    clock, consumed, closed = [100.0], [], []
    monkeypatch.setattr(supabase_auth, "monotonic", lambda: clock[0])

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(20):
                clock[0] += 0.75
                consumed.append(1)
                yield b" "

        def close(self):
            closed.append(1)

    subject = supabase_auth.SupabaseTokenVerifier(
        ISSUER,
        "authenticated",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/json"}, stream=Slow()
            )
        ),
    )
    with pytest.raises(TokenVerifierUnavailable):
        subject.verify(token(signing))
    assert len(consumed) == 3
    assert closed


@pytest.mark.parametrize("missing", ["iss", "aud", "sub", "exp", "iat"])
def test_required_claim_cannot_be_omitted(signing, missing):
    payload = jwt.decode(token(signing), options={"verify_signature": False})
    del payload[missing]
    raw = jwt.encode(payload, signing[0], algorithm=signing[1], headers={"kid": "key-1"})
    with pytest.raises(TokenVerificationError):
        verifier(signing).verify(raw)


def test_service_failure_uses_safe_503_without_database(monkeypatch):
    from fastapi import HTTPException

    from app.auth import TokenVerifierUnavailable
    from app.dependencies import get_tenant_context

    class Unavailable:
        def verify(self, _):
            raise TokenVerifierUnavailable("private-url-and-token")

    with pytest.raises(HTTPException) as error:
        get_tenant_context("Bearer token", Unavailable())
    assert error.value.status_code == 503
    assert "private" not in str(error.value.detail)


def test_valid_but_oversized_token_is_rejected_before_key_fetch(signing):
    def forbidden(_):
        pytest.fail("Oversized token fetched keys")

    large = token(signing, claims={"padding": "x" * 16384})
    with pytest.raises(TokenVerificationError):
        verifier(signing, handler=forbidden).verify(large)


def test_valid_but_oversized_key_set_is_not_accepted(signing):
    from app.auth import TokenVerifierUnavailable

    with pytest.raises(TokenVerifierUnavailable):
        verifier(
            signing,
            handler=lambda _: httpx.Response(
                200,
                json={
                    "keys": [signing[2]],
                    "padding": "x" * 65536,
                },
            ),
        ).verify(token(signing))


def test_excessively_nested_json_fails_safely(signing):
    from app.auth import TokenVerifierUnavailable

    nesting = "[" * 1100 + "0" + "]" * 1100
    header = '{"alg":"' + signing[1] + '","kid":"key-1","nested":' + nesting + "}"
    parts = token(signing).split(".")
    parts[0] = base64.urlsafe_b64encode(header.encode()).decode().rstrip("=")
    with pytest.raises(TokenVerificationError):
        verifier(signing).verify(".".join(parts))
    with pytest.raises(TokenVerifierUnavailable):
        verifier(
            signing,
            handler=lambda _: httpx.Response(
                200,
                content=nesting,
                headers={
                    "content-type": "application/json",
                },
            ),
        ).verify(token(signing))


def test_malformed_public_key_fails_without_publishing_partial_refresh(signing, monkeypatch):
    from app import supabase_auth
    from app.auth import TokenVerifierUnavailable

    clock, calls = [100.0], []
    monkeypatch.setattr(supabase_auth, "monotonic", lambda: clock[0])
    broken = {**signing[2], "kid": "broken"}
    del broken["x" if signing[1] == "ES256" else "n"]

    def service(_):
        calls.append(1)
        keys = [signing[2]] if len(calls) == 1 else [{**signing[2], "kid": "new"}, broken]
        return httpx.Response(200, json={"keys": keys})

    subject = verifier(signing, handler=service)
    subject.verify(token(signing))
    clock[0] = 130.0
    for _ in range(2):
        with pytest.raises(TokenVerifierUnavailable):
            subject.verify(token(signing, headers={"kid": "new"}))
    assert subject.verify(token(signing)).user_id == USER
    assert len(calls) == 2
    # A failed refresh must not move the original set's expiry from 400 to 430.
    clock[0] = 400.0
    with pytest.raises(TokenVerifierUnavailable):
        subject.verify(token(signing))
    assert len(calls) == 3


def test_refresh_wait_is_bounded_and_failed_fetch_is_shared(signing):
    from app.auth import TokenVerifierUnavailable

    entered, release = Event(), Event()
    calls = []

    def service(_):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return httpx.Response(503)

    subject = verifier(signing, handler=service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(subject.verify, token(signing))
        assert entered.wait(1)
        second = pool.submit(subject.verify, token(signing))
        try:
            # The second call must finish while the first transport stays blocked.
            with pytest.raises(TokenVerifierUnavailable):
                second.result(timeout=2)
        finally:
            release.set()
        with pytest.raises(TokenVerifierUnavailable):
            first.result()
    for _ in range(3):
        with pytest.raises(TokenVerifierUnavailable):
            subject.verify(token(signing))
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failure_is_safe_and_cools_down(signing, failure):
    from app.auth import TokenVerifierUnavailable

    calls = []

    def service(_):
        calls.append(1)
        raise failure("private identity URL")

    subject = verifier(signing, handler=service)
    for _ in range(2):
        with pytest.raises(TokenVerifierUnavailable, match="^Identity verification unavailable.$"):
            subject.verify(token(signing))
    assert len(calls) == 1


def test_supported_maximum_key_count_is_usable(signing):
    keys = [{**signing[2], "kid": f"key-{index + 1}"} for index in range(32)]
    subject = verifier(signing, handler=lambda _: httpx.Response(200, json={"keys": keys}))
    assert subject.verify(token(signing)).org_id == ORG
