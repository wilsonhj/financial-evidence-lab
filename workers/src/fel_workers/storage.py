"""Local-directory storage provider (frozen ``StorageProvider`` protocol).

Durable, content-addressed blob storage rooted at a local directory
(``FEL_STORAGE_DIR`` in the worker entrypoint). This is the live-mode
binding for single-node deployments and development against real EDGAR
data: unlike ``MockStorageProvider``, blobs survive the process, so the
``storage_key``/``canonical_text_key`` values persisted in the database
remain resolvable and citations can be served.

Immutability contract (mirrors ``fel_providers.mocks.MockStorageProvider``
exactly): a put to an existing key with identical bytes is a no-op; a put
to an existing key with different bytes raises ``ValueError``. Keys are
content-addressed (``raw/sha256/<hex>``, ...), so a conflicting rewrite is
always a corruption signal, never a legitimate update.

This module also owns the worker's process-level database-role binding
(:func:`apply_worker_db_role`, issue #190) — the one runtime switch every
worker connection passes through — so the entrypoint and the consumer's
heartbeat connection factory can share it without importing each other.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class LocalDirStorageProvider:
    """Immutable content-addressed object store on the local filesystem."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        """Resolve a storage key to a path strictly inside the root.

        Keys are slash-separated relative identifiers; anything absolute or
        escaping the root (``..``) fails closed.
        """
        if not key:
            raise ValueError("storage key must be non-empty")
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return candidate

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError(f"immutable key already exists: {key}")
            return path.as_uri()  # identical rewrite: no-op
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so readers never observe a partial blob.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".put-")
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        return path.as_uri()

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def signed_url(self, key: str, *, expires_seconds: int) -> str:
        """Local files have no signing authority; return a deterministic
        pseudo-signed file URL (same shape as the mock's) so callers relying
        on the protocol keep working in single-node deployments."""
        path = self._path(key)
        token = hashlib.sha256(f"{key}:{expires_seconds}".encode()).hexdigest()[:16]
        return f"{path.as_uri()}?sig={token}&exp={expires_seconds}"


# ---------------------------------------------------------------------------
# Worker database role (issue #190, ADR-0013)
# ---------------------------------------------------------------------------
#
# The job path has its own least-privilege database role (`fel_worker`,
# migration 0008): no DELETE, no DDL, no BYPASSRLS. Adopting it is an OPT-IN
# rollout switch rather than a hard cutover, because a grant the derivation
# missed would fail live jobs with 42501: with ``FEL_WORKER_DB_ROLE`` unset
# the worker keeps connecting exactly as before, and with it set every worker
# connection runs ``SET ROLE <role>`` immediately after connect.
#
# It lives here, next to the other process-level runtime binding, so the ONE
# place worker connections are made (``fel_workers.__main__.run_main``) and
# the heartbeat connection factory in ``consumer.py`` can share it without
# either importing the other.

_ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

WORKER_DB_ROLE_ENV = "FEL_WORKER_DB_ROLE"

log = logging.getLogger("fel_workers.storage")


def worker_db_role() -> str | None:
    """Return the configured worker database role, or ``None`` when unset.

    The value is interpolated into ``SET ROLE`` (Postgres does not accept a
    bind parameter there), so it is validated against ``^[a-z_][a-z0-9_]*$``
    — the shape of an unquoted SQL identifier — and anything else raises
    rather than being quoted-and-hoped. An operator typo must not become an
    injection point on the process's own connection string.
    """
    raw = os.environ.get(WORKER_DB_ROLE_ENV)
    if raw is None:
        return None
    role = raw.strip()
    if not role:
        return None
    if not _ROLE_NAME_RE.fullmatch(role):
        raise RuntimeError(
            f"{WORKER_DB_ROLE_ENV} must match ^[a-z_][a-z0-9_]*$ (an unquoted"
            f" SQL identifier); got {raw!r}. Refusing to start."
        )
    return role


def apply_worker_db_role(conn: Any) -> str | None:
    """``SET ROLE`` on ``conn`` when ``FEL_WORKER_DB_ROLE`` is configured.

    Returns the role that was adopted, or ``None`` when the switch is unset
    (current behaviour: the connection keeps the login role's privileges).
    Safe to call on any DB-API connection; it is deliberately a no-op rather
    than an error when unconfigured, so callers need no branch of their own.
    """
    role = worker_db_role()
    if role is None:
        return None
    conn.execute(f"SET ROLE {role}")  # noqa: S608 — validated identifier above
    log.info("worker database connection adopted role %s", role)
    return role
