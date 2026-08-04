"""Redacted extraction run events (never prompts / secrets).

Source text is redacted too, with one deliberate and bounded exception: a
``step_completed`` event's ``stage_output`` is the durable checkpoint payload
(frozen migration 0004 has no ``steps.output`` column), so it carries the pinned
span text and the stage payloads verbatim — see ``redact_event_payload``.
Everywhere else, in every other event type, and in **every** log line, prompts,
messages, source text and secrets are stripped.

Two entry points, deliberately not one:

* :func:`redact_event_payload` — the event sink (``MemoryEventStore.append`` and
  ``PostgresEventStore.append``). Takes ``event_type``, and grants the
  ``stage_output`` exemption only to ``step_completed``.
* :func:`redact_log_payload` — the log sink (``telemetry.emit``). Has no
  exemption of any kind and cannot be given one.

They are separate functions because the exemption's whole justification is that
``extraction_run_events`` is an org-scoped, RLS-protected durable record that a
resume reads back and re-hashes. A log line is none of those things: process
stdout is not RLS'd and nothing rehydrates from it, so filing text there would
be a real leak rather than a bounded false-guarantee. When both sinks shared one
function, telemetry was one accidental ``stage_output`` field away from
inheriting an exemption written for a database row (ADR-0009).
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

    Drops known sensitive keys and truncates unexpected long strings, with one
    exception: on a ``step_completed`` event, the ``stage_output`` subtree passes
    through **untouched**. Migration 0004 has no ``steps.output`` column, so that
    subtree IS the durable stage output, and every string in it is either
    restored verbatim on resume or hashed. Altering any of them — by truncation
    or by substitution — corrupts a resumed run silently. Precisely, inside
    ``stage_output``:

    * ``workflow._restore_output`` rebuilds ``EvidenceBlock.text`` (checked
      against ``text_hash``), ``state.classification``, ``state.candidates``,
      ``state.raw_proposals`` and ``state.normalized`` — the last two being whole
      extraction payloads, prose fields included.
    * ``validate/pipeline._build_draft`` then hashes those payloads: ``hash_json``
      over every field (``raw_payload_hash``, and ``proposal_id_for`` on top of
      it) and ``sha256_hex(definition)`` (``definition_hash``).
    * ``hashing.stage_input_hash`` hashes the same payloads again as the
      ``normalize`` / ``validate`` stage inputs, so an altered string breaks
      checkpoint identity as well as the proposal ids.

    The exemption is **positional, and total**. Two earlier attempts scoped it by
    field name and both leaked: first only ``text`` was exempt, so ``definition``
    and ``description`` prose stayed truncated; then truncation was suppressed
    wholesale but *substitution* was not, so a ``qualifiers``/``dimensions`` key
    an issuer happened to name ``token`` — or a payload field named ``raw`` —
    still became ``"[redacted]"`` and still broke ``raw_payload_hash`` (PR #145
    review M4). ``dimensions`` and ``qualifiers`` hold issuer-supplied keys with
    arbitrary names, which is exactly why no per-key rule can work here: the
    check has to be *where the data sits*, not *what it is called*.

    Nothing under ``stage_output`` needs a key-based rule anyway.
    ``serialize_stage_output`` serializes one stage's return value — evidence
    blocks, classification, candidates, and normalized payloads. Provider
    credentials and prompts are never part of a stage's return; they live on the
    provider call, and ``model_step`` (which does carry per-attempt request
    hashes) is a *sibling* of ``stage_output``, not inside it, so it is still
    redacted normally.

    Other event types get no exemption even if they somehow carry a
    ``stage_output`` key: the argument above is specifically about the one
    payload a resume reads back. The exemption is also applied only at the top
    level of that payload, which is the only place ``workflow`` writes the key —
    a nested ``stage_output`` deeper in some future payload is not the durable
    checkpoint and gets no pass.
    """
    if event_type != "step_completed":
        return _redact(payload)
    exempt = payload.get("stage_output")
    if not isinstance(exempt, (dict, list)):
        return _redact(payload)
    # Redact everything except the checkpoint subtree, then reattach it verbatim.
    # Splitting it out rather than special-casing inside `_redact` is what makes
    # the guarantee structural: no rule added to `_redact` later can reach it.
    rest = _redact({k: v for k, v in payload.items() if k != "stage_output"})
    return {**rest, "stage_output": exempt}


def redact_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact a payload bound for a log line — no exemptions, ever.

    Separate from :func:`redact_event_payload` on purpose. The ``stage_output``
    exemption is justified by properties a log line does not have: an
    org-scoped RLS'd table that a resume reads back and re-hashes. Process
    stdout is not tenant-scoped and nothing rehydrates from it, so the same
    filing text there is a genuine leak rather than a bounded false guarantee
    (``spec.md:180``, ``OPERATOR.md:16``). Keeping the exemption structurally
    unreachable from this path is cheaper than remembering not to pass a
    checkpoint payload to a logger (ADR-0009).
    """
    return _redact(payload)


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Unconditional redaction: sensitive keys masked, long strings truncated.

    Has no notion of an exemption, by design — the checkpoint carve-out is
    applied by ``redact_event_payload`` *around* this function, never inside it.
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
