"""Fast diagnostics for the publish-race lock wait (#230)."""

from __future__ import annotations

import warnings

import pytest

from . import test_ingestion_pipeline as ingestion_pipeline
from .test_ingestion_pipeline import _wait_for_publish_lock


class _Connection:
    def __init__(self, waiting: int) -> None:
        self.waiting = waiting
        self.calls = 0

    def execute(self, query: str):
        self.calls += 1
        assert "FROM pg_locks" in query
        assert "a.datname = current_database()" in query
        assert "a.pid <> pg_backend_pid()" in query
        return self

    def fetchone(self) -> tuple[int]:
        return (self.waiting,)


class _Thread:
    def __init__(self) -> None:
        self.joins = 0

    def join(self, *, timeout: float) -> None:
        assert timeout == 0.02
        self.joins += 1

    def is_alive(self) -> bool:
        return True


def test_publish_lock_wait_warns_when_predicate_never_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(waiting=0)
    thread = _Thread()
    monotonic = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr(ingestion_pipeline.time, "monotonic", monotonic.__next__)
    with pytest.warns(UserWarning, match=r"pg_locks.*0\.001s"):
        observed = _wait_for_publish_lock(connection, thread, timeout_seconds=0.001)

    assert observed is False
    assert connection.calls == 1
    assert thread.joins == 1


def test_publish_lock_wait_is_silent_when_predicate_matches() -> None:
    connection = _Connection(waiting=1)
    thread = _Thread()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        observed = _wait_for_publish_lock(connection, thread, timeout_seconds=1.0)

    assert observed is True
    assert connection.calls == 1
    assert thread.joins == 0
