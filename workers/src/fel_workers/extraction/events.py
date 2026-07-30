"""Redacted extraction run events (never prompts / secrets).

Source text is redacted too, with one deliberate and bounded exception: a
``step_completed`` event's ``stage_output`` is the durable checkpoint payload
(frozen migration 0004 has no ``steps.output`` column), so it carries the pinned
span text and the stage payloads verbatim — see ``redact_payload``. Prompts,
messages and secrets are stripped everywhere, ``stage_output`` included.
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


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop known sensitive keys and truncate unexpected long strings.

    Checkpoint payloads under ``stage_output`` are the exception, and they are
    exempted from *truncation* wholesale rather than key by key: migration 0004
    has no ``steps.output`` column, so the ``step_completed`` event payload IS the
    durable stage output, and every string in it is either restored verbatim on
    resume or hashed. Truncating any of them corrupts a resumed run silently.
    Precisely, inside ``stage_output``:

    * ``workflow._restore_output`` rebuilds ``EvidenceBlock.text`` (checked
      against ``text_hash``), ``state.classification``, ``state.candidates``,
      ``state.raw_proposals`` and ``state.normalized`` — the last two being whole
      extraction payloads, prose fields included.
    * ``validate/pipeline._build_draft`` then hashes those payloads: ``hash_json``
      over every field (``raw_payload_hash``, and ``proposal_id_for`` on top of
      it) and ``sha256_hex(definition)`` (``definition_hash``).
    * ``hashing.stage_input_hash`` hashes the same payloads again as the
      ``normalize`` / ``validate`` stage inputs, so a truncated string breaks
      checkpoint identity as well as the proposal ids.

    That set is not a closed list of field names: ``dimensions`` and
    ``qualifiers`` carry issuer-supplied keys with arbitrary values and are
    hashed too, so any per-key allowlist would miss them — which is how
    ``description`` / ``definition`` prose stayed truncated while only ``text``
    was exempt. The rule is therefore positional: no length truncation anywhere
    under ``stage_output``. Redaction of sensitive keys still applies there, and
    truncation still applies to every other (genuinely incidental) event string.
    """
    return _redact(payload, checkpoint=False)


def _redact(payload: dict[str, Any], *, checkpoint: bool) -> dict[str, Any]:
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
        if lowered in _REDACT_KEYS:
            if checkpoint and lowered == "text" and isinstance(value, str):
                # Span text survives redaction inside a checkpoint payload: it is
                # restored verbatim and the stored text_hash must keep describing it.
                cleaned[key] = value
            else:
                cleaned[key] = "[redacted]"
            continue
        if isinstance(value, dict):
            cleaned[key] = _redact(value, checkpoint=checkpoint)
        elif isinstance(value, list):
            cleaned[key] = [
                (_redact(v, checkpoint=checkpoint) if isinstance(v, dict) else v) for v in value
            ]
        elif not checkpoint and isinstance(value, str) and len(value) > 256:
            cleaned[key] = value[:64] + "…[truncated]"
        else:
            cleaned[key] = value
    return cleaned


def _redact_stage_output(value: dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
    if isinstance(value, list):
        return [_redact(v, checkpoint=True) if isinstance(v, dict) else v for v in value]
    return _redact(value, checkpoint=True)


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
