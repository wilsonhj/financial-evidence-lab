"""The worker module entrypoint: heartbeat mode terminates cleanly and the
``run`` job-consumer mode (finding 4) wires the queue loop."""

from __future__ import annotations

import os

import pytest

from fel_workers.__main__ import main, parse_run_args, run_main


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


@pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)
def test_run_mode_drains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m fel_workers run` binds the mock providers by default and
    exits cleanly once the bounded iteration budget is spent."""
    monkeypatch.setenv("FEL_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    assert run_main(["--max-iterations", "1", "--queue", "entrypoint-test"]) == 0
