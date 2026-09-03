"""Structured, redacted telemetry (T0403), mirroring the extraction-worker pattern.

Events carry ids, counts, durations and error codes — never node values, labels
or free text. Redaction is unconditional: sensitive keys are masked and long
strings truncated before a payload reaches any sink. The default sink writes a
single structured ``logging`` line; tests and hosts may inject another sink.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger("fel_calculation_engine.telemetry")

_REDACT_KEYS = frozenset(
    {
        "label",
        "text",
        "content",
        "notes",
        "prompt",
        "messages",
        "raw",
        "instructions",
        "value",
        "values",
        "secret",
        "api_key",
        "password",
        "token",
    }
)
_MAX_STRING = 256


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + "...[truncated]"
    return value


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Mask sensitive keys (recursively) and truncate long strings. No exemptions."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if (
            lowered in _REDACT_KEYS
            or "secret" in lowered
            or "password" in lowered
            or "token" in lowered
        ):
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = _redact_value(value)
    return cleaned


class TelemetrySink(Protocol):
    def emit(self, payload: dict[str, Any]) -> None: ...


class LoggingSink:
    def emit(self, payload: dict[str, Any]) -> None:
        log.info("calc_telemetry %s", payload)


class RecordingSink:
    """Keeps every emitted (already redacted) payload in memory."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)


DEFAULT_SINK: TelemetrySink = LoggingSink()


def emit(sink: TelemetrySink | None, event: str, **fields: Any) -> None:
    (sink or DEFAULT_SINK).emit(redact({"event": event, **fields}))


__all__ = ["DEFAULT_SINK", "LoggingSink", "RecordingSink", "TelemetrySink", "emit", "redact"]
