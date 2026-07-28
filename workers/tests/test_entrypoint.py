"""The worker module entrypoint: heartbeat mode terminates cleanly, the
``run`` job-consumer mode (finding 4) wires the queue loop, live-mode
provider binding fails closed without durable storage (re-review finding 2),
and the structured-model binding fails closed without an explicit opt-in."""

from __future__ import annotations

import contextlib
import os
import pathlib
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers.__main__ import (
    EXTRACTION_QUEUE,
    build_run_providers,
    build_structured_llm,
    main,
    parse_run_args,
    run_main,
)
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


def _capture_run_worker_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub out the queue loop and the database so ``run_main`` can be run for
    its WIRING only: returns the kwargs it passed to ``run_worker``."""
    captured: dict[str, Any] = {}

    def _fake_run_worker(*args: Any, **kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    @contextlib.contextmanager
    def _fake_connect(*args: Any, **kwargs: Any) -> Iterator[object]:
        yield object()

    monkeypatch.setattr("fel_workers.consumer.run_worker", _fake_run_worker)
    monkeypatch.setattr(psycopg, "connect", _fake_connect)
    return captured


def test_run_main_binds_no_model_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """No FEL_ALLOW_MOCK_LLM => no structured model is bound at all.

    The mock model answers every extraction_run with fabricated financials
    (a fixed $100m ARR proposal against fixture span/document ids). Binding
    it unconditionally meant a production worker persisted those into a real
    tenant's needs_review queue, indistinguishable from genuine output.
    """
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert captured["structured_llm"] is None


def test_run_main_binds_mock_model_with_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEL_ALLOW_MOCK_LLM=1 is the explicit opt-in the CI/mock smoke path uses."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert isinstance(captured["structured_llm"], MockStructuredLLMProvider)


def test_build_structured_llm_rejects_typo_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-in shares the strict mode-flag parser: a typo fails closed
    rather than silently reading as unset."""
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "ture")
    with pytest.raises(RuntimeError) as excinfo:
        build_structured_llm()
    assert "FEL_ALLOW_MOCK_LLM" in str(excinfo.value)


def test_extraction_queue_literal_matches_handler_constant() -> None:
    """The entrypoint names the extraction queue as a literal (like the
    'ingestion' argparse default) — this pins it to the handler's constant so
    a rename cannot silently disarm the startup gate."""
    from fel_workers.extraction.handler import DEFAULT_EXTRACTION_QUEUE

    assert EXTRACTION_QUEUE == DEFAULT_EXTRACTION_QUEUE


@pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)
def test_run_mode_drains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m fel_workers run` binds the mock providers by default and
    exits cleanly once the bounded iteration budget is spent."""
    monkeypatch.setenv("FEL_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    assert run_main(["--max-iterations", "1", "--queue", "entrypoint-test"]) == 0
