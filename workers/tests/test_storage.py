"""LocalDirStorageProvider: durable local blobs under the frozen
StorageProvider protocol, with the mock's exact immutability contract
(re-review finding 2)."""

from __future__ import annotations

import pathlib

import pytest

from fel_providers.interfaces import StorageProvider
from fel_workers.storage import LocalDirStorageProvider


def test_put_get_roundtrip_persists_across_instances(tmp_path: pathlib.Path) -> None:
    provider = LocalDirStorageProvider(tmp_path)
    url = provider.put("raw/sha256/deadbeef", b"filing bytes")
    assert url.startswith("file://")
    assert provider.get("raw/sha256/deadbeef") == b"filing bytes"
    # Durability is the whole point: a fresh instance (new process) still
    # resolves the key — unlike the in-memory mock.
    reopened = LocalDirStorageProvider(tmp_path)
    assert reopened.get("raw/sha256/deadbeef") == b"filing bytes"


def test_identical_rewrite_is_a_noop(tmp_path: pathlib.Path) -> None:
    provider = LocalDirStorageProvider(tmp_path)
    first = provider.put("raw/sha256/cafe", b"same bytes")
    second = provider.put("raw/sha256/cafe", b"same bytes")
    assert first == second
    assert provider.get("raw/sha256/cafe") == b"same bytes"


def test_conflicting_rewrite_raises(tmp_path: pathlib.Path) -> None:
    provider = LocalDirStorageProvider(tmp_path)
    provider.put("raw/sha256/f00d", b"original")
    with pytest.raises(ValueError, match="immutable key already exists"):
        provider.put("raw/sha256/f00d", b"DIFFERENT")
    assert provider.get("raw/sha256/f00d") == b"original", "failed put must not clobber"


def test_keys_escaping_the_root_fail_closed(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "store"
    provider = LocalDirStorageProvider(root)
    with pytest.raises(ValueError, match="escapes the storage root"):
        provider.put("../outside", b"x")
    with pytest.raises(ValueError, match="non-empty"):
        provider.get("")


def test_signed_url_is_deterministic_and_scoped(tmp_path: pathlib.Path) -> None:
    provider = LocalDirStorageProvider(tmp_path)
    provider.put("raw/sha256/beef", b"data")
    url = provider.signed_url("raw/sha256/beef", expires_seconds=60)
    assert url == provider.signed_url("raw/sha256/beef", expires_seconds=60)
    assert "sig=" in url and "exp=60" in url


def test_satisfies_frozen_storage_provider_protocol(tmp_path: pathlib.Path) -> None:
    provider: StorageProvider = LocalDirStorageProvider(tmp_path)
    assert provider.put("k", b"v") and provider.get("k") == b"v"
