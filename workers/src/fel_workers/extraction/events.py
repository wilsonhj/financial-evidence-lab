"""Redacted extraction run events (never prompts, secrets, or source text).

The event stream is metadata-only: IDs, counts, hashes, states and redacted
errors. There is no exemption and no carve-out, which is the whole point —
``specs/003-agentic-extraction/data-model.md``, the frozen
``extraction-event.schema.json`` and the shipped generated client all publish
that guarantee, and this module is where it is enforced.

It was not always true. Until ADR-0011 a ``step_completed`` event's
``stage_output`` key carried the pinned span text and the stage payloads
verbatim, because frozen migration 0004 had no ``steps.output`` column and the
event payload was the only durable carrier a resume could read back. Migration
0006 adds that column, so the checkpoint no longer rides on the event and the
positional exemption ``redact_event_payload`` used to grant is deleted rather
than narrowed (ADR-0011 decision item 5).

Two entry points remain, deliberately not one:

* :func:`redact_event_payload` — the event sink (``MemoryEventStore.append`` and
  ``PostgresEventStore.append``).
* :func:`redact_log_payload` — the log sink (``telemetry.emit``).

They now do the same thing. They are kept separate because their justifications
are different — an event row is org-scoped and RLS-protected, a log line is
neither — so a future exemption argued for one sink cannot silently be inherited
by the other. That is exactly how the ``stage_output`` carve-out nearly reached
``telemetry`` when both sinks shared one function (ADR-0009).
"""

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


def redact_event_payload(payload: dict[str, Any], *, event_type: str) -> dict[str, Any]:
    """Redact an event payload bound for ``extraction_run_events``.

    Drops known sensitive keys and truncates unexpected long strings, over the
    WHOLE payload — every key, at every depth. ``event_type`` is retained in the
    signature (and unused) because it is what a future rule would have to be
    written against, and because every call site already passes it; it must not
    become a lever for re-introducing an exemption.

    A stage's result is no longer here to protect. It lives in
    ``extraction_run_steps.output`` (migration 0006), written in the same
    transaction as its ``output_hash`` and re-hashed on resume, so nothing in
    this payload is restored verbatim or hashed any more: ``step_completed``
    carries the step name, the input/output hashes and counts, and that is all
    (``workflow._run_stage``). Truncating or masking a string here can therefore
    no longer corrupt a resumed run, which is precisely what the old exemption
    existed to prevent.
    """
    del event_type  # single mode: see the docstring, and ADR-0011 item 5.
    return _redact(payload)


def redact_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact a payload bound for a log line — no exemptions, ever.

    Kept separate from :func:`redact_event_payload` even though the two are now
    identical. Process stdout is not tenant-scoped and nothing rehydrates from
    it, so an argument that ever justifies relaxing the event sink cannot
    justify relaxing this one (``spec.md:180``, ``OPERATOR.md:16``). Keeping the
    two paths distinct is cheaper than remembering not to pass a payload with
    source text to a logger (ADR-0009, ADR-0011).
    """
    return _redact(payload)


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Unconditional redaction: sensitive keys masked, long strings truncated.

    Has no notion of an exemption, by design, and both public helpers are now
    thin wrappers over it.
    """
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if (
            lowered in {"secret", "api_key", "password", "token"}
            or "secret" in lowered
            or "password" in lowered
            or lowered in _REDACT_KEYS
        ):
            cleaned[key] = "[redacted]"
            continue
        if isinstance(value, dict):
            cleaned[key] = _redact(value)
        elif isinstance(value, list):
            cleaned[key] = [(_redact(v) if isinstance(v, dict) else v) for v in value]
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
            payload=redact_event_payload(payload, event_type=event_type),
            id=len(self.events) + 1,
        )
        self.events.append(event)
        return event


__all__ = [
    "ALLOWED_EVENT_TYPES",
    "ExtractionEvent",
    "MemoryEventStore",
    "redact_event_payload",
    "redact_log_payload",
]
