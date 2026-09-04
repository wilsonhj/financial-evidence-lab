"""#203: optional Sentry initialisation. No database needed."""

from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType
from typing import Any

import pytest

from app.observability import configure_error_reporting, report_exception


class _FakeSentry(ModuleType):
    def __init__(self) -> None:
        super().__init__("sentry_sdk")
        self.calls: list[dict[str, Any]] = []
        self.captured: list[BaseException] = []

    def init(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def capture_exception(self, exc: BaseException) -> None:
        self.captured.append(exc)


def test_no_dsn_never_touches_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default deployment reports nothing off-box."""
    monkeypatch.delenv("FEL_SENTRY_DSN", raising=False)
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_error_reporting()

    assert fake.calls == []


def test_dsn_initialises_the_sdk_with_pii_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_SENTRY_DSN", "https://public@sentry.invalid/42")
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_error_reporting()

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["dsn"] == "https://public@sentry.invalid/42"
    # Financial documents and tenant claims are never automatic error-report
    # payloads; this flag is the whole reason the call is written out here.
    assert call["send_default_pii"] is False


def test_dsn_without_the_sdk_warns_and_keeps_booting(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("FEL_SENTRY_DSN", "https://public@sentry.invalid/42")
    monkeypatch.delitem(sys.modules, "sentry_sdk", raising=False)
    real_import = builtins.__import__

    def _refuse_sentry(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentry_sdk":
            raise ImportError("No module named 'sentry_sdk'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _refuse_sentry)

    with caplog.at_level(logging.WARNING, logger="fel_api"):
        configure_error_reporting()

    assert any("sentry-sdk" in record.getMessage() for record in caplog.records)


def test_report_exception_forwards_to_the_sdk_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastAPI's catch-all turns exceptions into JSON inside call_next, so
    Sentry's default integrations never see them. The handler must capture."""
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    boom = RuntimeError("pipeline exploded")
    report_exception(boom)
    assert fake.captured == [boom]


def test_report_exception_is_a_noop_without_the_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "sentry_sdk", raising=False)
    real_import = builtins.__import__

    def _refuse_sentry(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentry_sdk":
            raise ImportError("No module named 'sentry_sdk'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _refuse_sentry)
    report_exception(RuntimeError("ignored"))
