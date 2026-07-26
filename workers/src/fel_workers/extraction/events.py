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
    """Drop known sensitive keys and truncate unexpected long strings."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in _REDACT_KEYS or any(part in lowered for part in ("secret", "password")):
            cleaned[key] = "[redacted]"
            continue
        if isinstance(value, dict):
            cleaned[key] = redact_payload(value)
        elif isinstance(value, list):
            cleaned[key] = [redact_payload(v) if isinstance(v, dict) else v for v in value]
        elif isinstance(value, str) and len(value) > 256:
            cleaned[key] = value[:64] + "…[truncated]"
        else:
            cleaned[key] = value
    return cleaned


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
