"""The worker module entrypoint: heartbeat mode terminates cleanly, the
``run`` job-consumer mode (finding 4) wires the queue loop, and live-mode
provider binding fails closed without durable storage (re-review finding 2)."""

from __future__ import annotations

import os
import pathlib

import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider
from fel_workers.__main__ import build_run_providers, main, parse_run_args, run_main
from fel_workers.ingestion.sec_client import LiveSecClient
from fel_workers.storage import LocalDirStorageProvider


def test_heartbeat_loop_bounded() -> None:
    assert main(max_beats=2, interval_seconds=0.0) == 0


def test_parse_run_args_defaults_and_overrides() -> None:
    defaults = parse_run_args([])
    assert defaults.max_iterations is None
    assert defaults.queue == "ingestion"
    custom = parse_run_args(["--max-iterations", "3", "--queue", "other"])
    assert custom.max_iterations == 3
    assert custom.queue == "other"


def test_run_mode_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_DATABASE_URL", raising=False)
    assert run_main(["--max-iterations", "1"]) == 2


def test_mock_mode_binds_mock_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_STORAGE_DIR", raising=False)
    sec, storage = build_run_providers()
    assert isinstance(sec, MockSecClient)
    assert isinstance(storage, MockStorageProvider)


def test_live_mode_without_storage_dir_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEL_SEC_LIVE=1 with no FEL_STORAGE_DIR must refuse to start: live
    ingestion over in-memory mock storage persists storage keys whose blobs
    die with the process, making citations unresolvable."""
    monkeypatch.setenv("FEL_SEC_LIVE", "1")
    monkeypatch.delenv("FEL_STORAGE_DIR", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        build_run_providers()
    assert "FEL_SEC_LIVE" in str(excinfo.value) and "FEL_STORAGE_DIR" in str(excinfo.value)


def test_run_main_live_without_storage_dir_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-closed check happens before any DB or network activity."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.setenv("FEL_SEC_LIVE", "1")
    monkeypatch.delenv("FEL_STORAGE_DIR", raising=False)
    assert run_main(["--max-iterations", "1"]) == 2


def test_live_mode_binds_local_dir_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Env-driven wiring only — LiveSecClient construction performs no
    network I/O, and no request is ever issued in this test."""
    monkeypatch.setenv("FEL_SEC_LIVE", "1")
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path / "blobs"))
    sec, storage = build_run_providers()
    assert isinstance(sec, LiveSecClient)
    assert isinstance(storage, LocalDirStorageProvider)
    storage.put("raw/sha256/abc", b"blob")
    assert storage.get("raw/sha256/abc") == b"blob"
    assert (tmp_path / "blobs" / "raw" / "sha256" / "abc").read_bytes() == b"blob"


@pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)
def test_run_mode_drains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m fel_workers run` binds the mock providers by default and
    exits cleanly once the bounded iteration budget is spent."""
    monkeypatch.setenv("FEL_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    assert run_main(["--max-iterations", "1", "--queue", "entrypoint-test"]) == 0
