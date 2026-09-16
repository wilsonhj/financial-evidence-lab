"""Offline authenticated credential encryption; authorization belongs to callers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from cryptography.fernet import MultiFernet


class CredentialCipherError(RuntimeError):
    """Fixed diagnostics with no underlying exception chain."""

    def __init__(self) -> None:
        super().__init__("Credential encryption operation failed")


@dataclass(frozen=True, repr=False)
class CipherContext:
    purpose: str
    provider: str
    user_id: str
    org_id: str
    credential_id: str
    credential_version: int

    def __repr__(self) -> str:
        return "CipherContext(<redacted>)"


def _context(context: CipherContext) -> dict[str, Any]:
    if type(context) is not CipherContext:
        raise ValueError("context")
    value = asdict(context)
    for field in ("purpose", "provider"):
        if (
            type(value[field]) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value[field]) is None
        ):
            raise ValueError("context")
    for field in ("user_id", "org_id", "credential_id"):
        raw = value[field]
        if type(raw) is not str or len(raw) != 36 or str(UUID(raw)) != raw:
            raise ValueError("context")
    version = value["credential_version"]
    if type(version) is not int or not 1 <= version <= 2**31 - 1:
        raise ValueError("context")
    return value


def _secret(secret: str) -> None:
    if type(secret) is not str or not 1 <= len(secret) <= 4096:
        raise ValueError("secret")
    if len(secret.encode("utf-8")) > 4096:
        raise ValueError("secret")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


class CredentialCipher:
    """Explicit keyring only. Returned plaintext is sensitive, never diagnostic data."""

    def __init__(self, keyring: list[bytes] | tuple[bytes, ...]) -> None:
        try:
            if type(keyring) not in (list, tuple) or not 1 <= len(keyring) <= 16:
                raise ValueError("keyring")
            if any(type(key) is not bytes or len(key) != 44 for key in keyring):
                raise ValueError("keyring")
            if len(set(keyring)) != len(keyring):
                raise ValueError("keyring")
            from cryptography.fernet import Fernet, MultiFernet

            self._cipher: MultiFernet = MultiFernet([Fernet(key) for key in keyring])
            return
        except Exception:
            failure = CredentialCipherError()
        raise failure

    def __repr__(self) -> str:
        return "CredentialCipher(<redacted>)"

    def seal(self, secret: str, context: CipherContext) -> bytes:
        try:
            identity = _context(context)
            _secret(secret)
            payload = json.dumps(
                {"schema": "credential-cipher/v1", "identity": identity, "secret": secret},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            return self._cipher.encrypt(payload)
        except Exception:
            failure = CredentialCipherError()
        raise failure

    def _decode(self, token: bytes, context: CipherContext) -> str:
        expected = _context(context)
        if type(token) is not bytes or not 1 <= len(token) <= 16384:
            raise ValueError("token")
        plaintext = self._cipher.decrypt(token)
        if len(plaintext) > 8192:
            raise ValueError("payload")
        value = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_object)
        if (
            type(value) is not dict
            or set(value) != {"schema", "identity", "secret"}
            or value["schema"] != "credential-cipher/v1"
            or type(value["identity"]) is not dict
        ):
            raise ValueError("payload")
        actual = _context(CipherContext(**value["identity"]))
        if actual != expected:
            raise ValueError("identity")
        secret = value["secret"]
        _secret(secret)
        return str(secret)

    def open(self, token: bytes, expected: CipherContext) -> str:
        try:
            return self._decode(token, expected)
        except Exception:
            failure = CredentialCipherError()
        raise failure

    def rotate(self, token: bytes, expected: CipherContext) -> bytes:
        try:
            self._decode(token, expected)
            return self._cipher.rotate(token)
        except Exception:
            failure = CredentialCipherError()
        raise failure
