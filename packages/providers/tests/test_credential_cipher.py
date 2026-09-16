"""Offline key custody primitive tests; all keys are generated and synthetic."""

import json
import traceback
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet, MultiFernet

from fel_providers.credential_cipher import CipherContext, CredentialCipher, CredentialCipherError

CONTEXT = CipherContext(
    purpose="provider-credential",
    provider="openrouter",
    user_id="11111111-1111-4111-8111-111111111111",
    org_id="22222222-2222-4222-8222-222222222222",
    credential_id="33333333-3333-4333-8333-333333333333",
    credential_version=1,
)
SECRET = "synthetic-private-credential"


def test_roundtrip_and_redacted_objects():
    key = Fernet.generate_key()
    cipher = CredentialCipher([key])
    token = cipher.seal(SECRET, CONTEXT)
    assert cipher.open(token, CONTEXT) == SECRET
    assert SECRET not in repr(cipher) + repr(CONTEXT)
    assert key.decode() not in repr(cipher)
    assert CONTEXT.user_id not in repr(CONTEXT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "other"),
        ("provider", "openai"),
        ("user_id", "44444444-4444-4444-8444-444444444444"),
        ("org_id", "44444444-4444-4444-8444-444444444444"),
        ("credential_id", "44444444-4444-4444-8444-444444444444"),
        ("credential_version", 2),
    ],
)
def test_each_identity_mismatch_fails(field, value):
    cipher = CredentialCipher([Fernet.generate_key()])
    with pytest.raises(CredentialCipherError):
        cipher.open(cipher.seal(SECRET, CONTEXT), replace(CONTEXT, **{field: value}))


def test_rotation_and_retirement():
    old, new = Fernet.generate_key(), Fernet.generate_key()
    original = CredentialCipher([old]).seal(SECRET, CONTEXT)
    rotating = CredentialCipher([new, old])
    rotated = rotating.rotate(original, CONTEXT)
    assert rotating.open(original, CONTEXT) == SECRET
    assert CredentialCipher([new]).open(rotated, CONTEXT) == SECRET
    assert Fernet(new).extract_timestamp(rotated) == Fernet(old).extract_timestamp(original)
    with pytest.raises(CredentialCipherError):
        CredentialCipher([old]).open(rotated, CONTEXT)
    with pytest.raises(CredentialCipherError):
        CredentialCipher([new]).open(original, CONTEXT)
    with pytest.raises(CredentialCipherError):
        rotating.rotate(original, replace(CONTEXT, purpose="other"))


@pytest.mark.parametrize("keys", [[], [b"bad"], ["not-bytes"], None, b"bad", [b"x"] * 17])
def test_invalid_keyrings(keys):
    with pytest.raises(CredentialCipherError):
        CredentialCipher(keys)


def test_duplicate_keyring():
    key = Fernet.generate_key()
    with pytest.raises(CredentialCipherError):
        CredentialCipher([key, key])


@pytest.mark.parametrize("secret", ["", "x" * 4097, "é" * 2049, "\ud800", None, b"secret"])
def test_secret_boundaries(secret):
    cipher = CredentialCipher([Fernet.generate_key()])
    with pytest.raises(CredentialCipherError):
        cipher.seal(secret, CONTEXT)


def test_utf8_exact_limit():
    cipher = CredentialCipher([Fernet.generate_key()])
    secret = "é" * 2048
    assert cipher.open(cipher.seal(secret, CONTEXT), CONTEXT) == secret


@pytest.mark.parametrize("token", [b"", b"bad", b"x" * 16385, "text", None])
def test_bad_tokens(token):
    with pytest.raises(CredentialCipherError):
        CredentialCipher([Fernet.generate_key()]).open(token, CONTEXT)


def test_tamper():
    cipher = CredentialCipher([Fernet.generate_key()])
    token = bytearray(cipher.seal(SECRET, CONTEXT))
    token[20] = ord("A") if token[20] != ord("A") else ord("B")
    with pytest.raises(CredentialCipherError):
        cipher.open(bytes(token), CONTEXT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "not-uuid"),
        ("org_id", ""),
        ("credential_id", 1),
        ("purpose", "x" * 65),
        ("provider", "https://bad"),
        ("credential_version", True),
        ("credential_version", 0),
    ],
)
def test_bad_context(field, value):
    with pytest.raises(CredentialCipherError):
        CredentialCipher([Fernet.generate_key()]).seal(SECRET, replace(CONTEXT, **{field: value}))


@pytest.mark.parametrize(
    "mutation", ["extra", "missing", "duplicate", "schema", "secret", "encoding"]
)
def test_authenticated_bad_payload(mutation):
    key = Fernet.generate_key()
    cipher = CredentialCipher([key])
    payload = Fernet(key).decrypt(cipher.seal(SECRET, CONTEXT))
    data = json.loads(payload)
    if mutation == "extra":
        data["unknown"] = SECRET
    elif mutation == "missing":
        del data["secret"]
    elif mutation == "schema":
        data["schema"] = "unknown"
    elif mutation == "secret":
        data["secret"] = "x" * 4097
    payload = json.dumps(data).encode()
    if mutation == "duplicate":
        payload = payload[:-1] + b',"secret":"duplicate"}'
    elif mutation == "encoding":
        payload = b"\xff"
    with pytest.raises(CredentialCipherError):
        cipher.open(Fernet(key).encrypt(payload), CONTEXT)


def test_exception_does_not_retain_library_diagnostics(monkeypatch):
    key = Fernet.generate_key()
    cipher = CredentialCipher([key])

    def hostile(*args, **kwargs):
        raise RuntimeError(SECRET + key.decode())

    monkeypatch.setattr(MultiFernet, "encrypt", hostile)
    with pytest.raises(CredentialCipherError) as caught:
        cipher.seal(SECRET, CONTEXT)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET not in rendered and key.decode() not in rendered


@pytest.mark.parametrize("operation", ["open", "rotate"])
def test_read_exception_chain_is_redacted(monkeypatch, operation):
    key = Fernet.generate_key()
    cipher = CredentialCipher([key])
    token = cipher.seal(SECRET, CONTEXT)

    def hostile(*args, **kwargs):
        raise ValueError(SECRET + key.decode())

    monkeypatch.setattr(MultiFernet, "decrypt", hostile)
    with pytest.raises(CredentialCipherError) as caught:
        getattr(cipher, operation)(token, CONTEXT)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert SECRET not in "".join(traceback.format_exception(caught.value))
