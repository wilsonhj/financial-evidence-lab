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
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


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
