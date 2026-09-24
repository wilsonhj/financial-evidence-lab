"""ADR-0025: bounded asymmetric verification; PostgreSQL owns membership/role."""

from __future__ import annotations

import json
import math
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt

from app.auth import TenantContext, TokenVerificationError, TokenVerifierUnavailable

ALGORITHMS = ("ES256", "RS256")


def _invalid() -> TokenVerificationError:
    return TokenVerificationError("Invalid access token.")


def _unavailable() -> TokenVerifierUnavailable:
    return TokenVerifierUnavailable("Identity verification unavailable.")


def _kid(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= 128


class SupabaseTokenVerifier:
    def __init__(
        self, issuer: str, audience: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        parsed = urlsplit(issuer)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in issuer
            or "#" in issuer
            or issuer.endswith("/")
            or any(c.isspace() for c in issuer)
            or not audience.strip()
        ):
            raise ValueError("Invalid identity configuration")
        # Validate malformed ports now, without interpreting token-provided URLs.
        _ = parsed.port
        self.issuer = issuer
        self.audience = audience
        self._url = issuer + "/.well-known/jwks.json"
        self._transport = transport
        self._cache: tuple[float, dict[str, jwt.PyJWK]] | None = None
        self._attempt: float | None = None
        self._failed = False
        self._lock = Lock()

    def verify(self, token: str) -> TenantContext:
        try:
            if len(token.encode()) > 16384 or token.count(".") != 2:
                raise _invalid()
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") not in ALGORITHMS
                or not _kid(header.get("kid"))
                or any(name in header for name in ("crit", "jku", "jwk", "x5u"))
                or header.get("b64", True) is not True
            ):
                raise _invalid()
            key = self._key(header["kid"])
            if header["alg"] != key.algorithm_name:
                raise _invalid()
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ALGORITHMS),
                issuer=self.issuer,
                audience=self.audience,
                leeway=30,
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat"],
                    "strict_aud": True,
                    "enforce_minimum_key_length": True,
                },
            )
            for name in ("exp", "iat", "nbf"):
                if name not in claims:
                    continue
                value = claims[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise _invalid()
                if isinstance(value, float) and (
                    not math.isfinite(value) or not value.is_integer()
                ):
                    raise _invalid()
            metadata = claims.get("app_metadata")
            if not isinstance(metadata, dict) or not isinstance(metadata.get("org_id"), str):
                raise _invalid()
            if not isinstance(claims["sub"], str):
                raise _invalid()
            return TenantContext(str(UUID(metadata["org_id"])), str(UUID(claims["sub"])), "viewer")
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise _invalid() from exc

    def _fresh(self) -> dict[str, jwt.PyJWK]:
        snapshot = self._cache
        return snapshot[1] if snapshot and monotonic() - snapshot[0] < 300 else {}

    def _key(self, kid: str) -> jwt.PyJWK:
        # An immutable cache snapshot lets known keys remain usable during refresh.
        key = self._fresh().get(kid)
        if key is not None:
            return key
        if not self._lock.acquire(timeout=1):
            raise _unavailable()
        try:
            current = self._fresh()
            if kid in current:
                return current[kid]
            if self._attempt is not None and monotonic() - self._attempt < 30:
                if current and not self._failed:
                    raise _invalid()
                raise _unavailable()
            self._attempt = monotonic()
            self._failed = True
            keys = self._fetch()
            self._cache = (monotonic(), keys)
            self._failed = False
            if kid not in keys:
                raise _invalid()
            return keys[kid]
        finally:
            self._lock.release()

    def _fetch(self) -> dict[str, jwt.PyJWK]:
        started = monotonic()
        try:
            with httpx.Client(
                transport=self._transport, timeout=1, follow_redirects=False
            ) as client:
                with client.stream(
                    "GET",
                    self._url,
                    headers={
                        "accept": "application/json",
                        "accept-encoding": "identity",
                    },
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";")[0].strip().lower()
                        not in ("application/json", "application/jwk-set+json")
                        or response.headers.get("content-encoding", "identity").lower()
                        != "identity"
                    ):
                        raise _unavailable()
                    body = bytearray()
                    chunks = response.iter_raw()
                    while True:
                        if monotonic() - started > 2:
                            raise _unavailable()
                        chunk = next(chunks, None)
                        if chunk is None:
                            break
                        if monotonic() - started > 2 or len(body) + len(chunk) > 65536:
                            raise _unavailable()
                        body.extend(chunk)
                    if monotonic() - started > 2:
                        raise _unavailable()
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
                raise _unavailable()
            if not 1 <= len(data["keys"]) <= 32:
                raise _unavailable()
            result: dict[str, jwt.PyJWK] = {}
            for raw in data["keys"]:
                if not isinstance(raw, dict) or not _kid(raw.get("kid")):
                    raise _unavailable()
                kid = raw["kid"]
                key_type = raw.get("kty")
                if not isinstance(key_type, str):
                    raise _unavailable()
                algorithm = {"RSA": "RS256", "EC": "ES256"}.get(key_type)
                if (
                    algorithm is None
                    or kid in result
                    or any(field in raw for field in ("d", "k", "p", "q", "dp", "dq", "qi", "oth"))
                    or (raw["kty"] == "EC" and raw.get("crv") != "P-256")
                    or raw.get("alg", algorithm) != algorithm
                    or raw.get("use", "sig") != "sig"
                    or raw.get("key_ops", ["verify"]) != ["verify"]
                ):
                    raise _unavailable()
                result[kid] = jwt.PyJWK.from_dict(raw, algorithm=algorithm)
            return result
        except (
            httpx.HTTPError,
            jwt.PyJWTError,
            ValueError,
            TypeError,
            OverflowError,
            RecursionError,
        ) as exc:
            raise _unavailable() from exc
