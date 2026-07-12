"""The worker module entrypoint runs and terminates cleanly."""

from __future__ import annotations

from fel_workers.__main__ import main


def test_heartbeat_loop_bounded() -> None:
    assert main(max_beats=2, interval_seconds=0.0) == 0
