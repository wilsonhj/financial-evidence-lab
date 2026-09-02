"""Worker health endpoint and optional Sentry init (#200, #203).

The endpoint exists to distinguish "idle" from "wedged": an empty queue and a
dead consumer loop look identical from outside the process. These tests bind
an EPHEMERAL port (0) so they never collide with a developer's local services
or with a parallel test run, and drive the server over real HTTP rather than
calling the handler directly — the status code is the contract a platform
health check consumes.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from fel_workers.__main__ import init_sentry, resolve_health_port
from fel_workers.health import Liveness, start_health_server


class FakeClock:
    """Monotonic clock the test advances by hand (no sleeping)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def served(clock: FakeClock) -> Iterator[tuple[Liveness, str]]:
    liveness = Liveness(queue="ingestion", monotonic=clock)
    server, _thread = start_health_server(liveness, port=0, host="127.0.0.1", max_age_seconds=30.0)
    port = server.server_address[1]
    try:
        yield liveness, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 — fixed localhost URL
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body else {}


def test_health_reports_ok_while_the_loop_is_turning(
    served: tuple[Liveness, str], clock: FakeClock
) -> None:
    liveness, base = served
    clock.now += 5.0
    liveness.touch()
    status, body = _get(f"{base}/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["queue"] == "ingestion"
    assert body["last_heartbeat_age_seconds"] == 0.0


def test_health_reports_503_once_the_loop_goes_stale(
    served: tuple[Liveness, str], clock: FakeClock
) -> None:
    """A worker whose loop stopped iterating must fail its probe.

    This is the whole point of the endpoint: without it a wedged consumer
    keeps a healthy container up and the queue drains only when someone
    notices their jobs never finished.
    """
    liveness, base = served
    liveness.touch()
    clock.now += 31.0
    status, body = _get(f"{base}/health")
    assert status == 503
    assert body["status"] == "stale"
    assert body["last_heartbeat_age_seconds"] == pytest.approx(31.0)


def test_unknown_paths_are_404(served: tuple[Liveness, str]) -> None:
    status, _ = _get(f"{served[1]}/metrics")
    assert status == 404


def test_age_is_measured_from_construction_before_the_first_touch(
    clock: FakeClock,
) -> None:
    """A process that never reaches its first iteration must go unhealthy.

    If the age were None/0 until the first touch, a worker that died during
    startup would report healthy forever.
    """
    liveness = Liveness(queue="ingestion", monotonic=clock)
    clock.now += 500.0
    status, body = liveness.snapshot(max_age_seconds=30.0)
    assert status == 503
    assert body["last_heartbeat_age_seconds"] == pytest.approx(500.0)


def test_health_port_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_WORKER_HEALTH_PORT", raising=False)
    assert resolve_health_port() is None
    monkeypatch.setenv("FEL_WORKER_HEALTH_PORT", " 8080 ")
    assert resolve_health_port() == 8080
    monkeypatch.setenv("FEL_WORKER_HEALTH_PORT", "http")
    with pytest.raises(RuntimeError, match="integer port"):
        resolve_health_port()
    monkeypatch.setenv("FEL_WORKER_HEALTH_PORT", "70000")
    with pytest.raises(RuntimeError, match="1..65535"):
        resolve_health_port()


# --------------------------------------------------------------------------
# Sentry (#203): optional, PII-free, and never silently absent.
# --------------------------------------------------------------------------


class _FakeSentry:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def init(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def test_sentry_is_not_initialised_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_SENTRY_DSN", raising=False)
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    assert init_sentry() is False
    assert fake.kwargs is None


def test_sentry_init_pins_pii_off_and_reads_the_sample_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_SENTRY_DSN", "https://public@sentry.invalid/1")
    monkeypatch.setenv("FEL_SENTRY_TRACES_SAMPLE_RATE", "0.25")
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    assert init_sentry() is True
    assert fake.kwargs == {
        "dsn": "https://public@sentry.invalid/1",
        "send_default_pii": False,
        "traces_sample_rate": 0.25,
    }


def test_sentry_traces_default_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_SENTRY_DSN", "https://public@sentry.invalid/1")
    monkeypatch.delenv("FEL_SENTRY_TRACES_SAMPLE_RATE", raising=False)
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    assert init_sentry() is True
    assert fake.kwargs is not None
    assert fake.kwargs["traces_sample_rate"] == 0.0


def test_missing_sdk_warns_instead_of_failing_the_worker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """sentry-sdk is not a worker dependency; a DSN without it must not crash
    the process — but it must not pass silently either, or an operator
    believes errors are reported when nothing is."""
    monkeypatch.setenv("FEL_SENTRY_DSN", "https://public@sentry.invalid/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    with caplog.at_level("WARNING"):
        assert init_sentry() is False
    assert "sentry-sdk" in caplog.text
