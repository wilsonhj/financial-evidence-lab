"""Redacted extraction run events (never source text / prompts / secrets)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

ALLOWED_EVENT_TYPES = frozenset(
    {
        "run_queued",
        "run_started",
        "step_started",
        "step_completed",
        "step_failed",
        "budget_updated",
        "proposals_persisted",
        "review_waiting",
        "review_completed",
        "run_succeeded",
        "run_failed",
        "run_cancelled",
        "heartbeat",
    }
)

# Keys that must never appear in event payloads (defense in depth).
_REDACT_KEYS = frozenset(
    {
        "text",
        "content",
        "prompt",
        "messages",
        "raw",
        "source_text",
        "instructions",
        "evidence_text",
        "secret",
        "api_key",
        "password",
        "token",
    }
)


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop known sensitive keys and truncate unexpected long strings.

    Checkpoint payloads under ``stage_output`` keep span ``text`` so crash-resume
    can restore evidence without a steps.output column (frozen migration 0004).
    Secrets are still stripped everywhere.
    """
    return _redact(payload, allow_span_text=False)


def _redact(payload: dict[str, Any], *, allow_span_text: bool) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if (
            lowered in {"secret", "api_key", "password", "token"}
            or "secret" in lowered
            or "password" in lowered
        ):
            cleaned[key] = "[redacted]"
            continue
        if key == "stage_output" and isinstance(value, (dict, list)):
            cleaned[key] = _redact_stage_output(value)
            continue
        if lowered in _REDACT_KEYS and not (allow_span_text and lowered == "text"):
            cleaned[key] = "[redacted]"
            continue
        if isinstance(value, dict):
            cleaned[key] = _redact(value, allow_span_text=allow_span_text)
        elif isinstance(value, list):
            cleaned[key] = [
                (_redact(v, allow_span_text=allow_span_text) if isinstance(v, dict) else v)
                for v in value
            ]
        elif isinstance(value, str) and len(value) > 256:
            cleaned[key] = value[:64] + "…[truncated]"
        else:
            cleaned[key] = value
    return cleaned


def _redact_stage_output(value: dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
    if isinstance(value, list):
        return [_redact(v, allow_span_text=True) if isinstance(v, dict) else v for v in value]
    return _redact(value, allow_span_text=True)


@dataclass
class ExtractionEvent:
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class MemoryEventStore:
    events: list[ExtractionEvent] = field(default_factory=list)

    def append(
        self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> ExtractionEvent:
        del org_id, run_id
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"unknown event_type {event_type!r}")
        event = ExtractionEvent(
            event_type=event_type,
            payload=redact_payload(payload),
            id=len(self.events) + 1,
        )
        self.events.append(event)
        return event


__all__ = [
    "ALLOWED_EVENT_TYPES",
    "ExtractionEvent",
    "MemoryEventStore",
    "redact_payload",
]
