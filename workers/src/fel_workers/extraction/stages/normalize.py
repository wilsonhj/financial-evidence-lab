"""``normalize`` — Decimal normalization of every raw proposal."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.normalize.pipeline import normalize_payload
from fel_workers.extraction.telemetry import emit
from fel_workers.extraction.types import NORMALIZER_BLOCKERS_KEY, WorkflowState


def stage_normalize(state: WorkflowState) -> dict[str, Any]:
    """Normalize every raw proposal, keeping the unnormalizable ones visible.

    Dropping a payload the normalizer rejects made it vanish with no blocker, no
    event and no counter: when every proposal hit that path the run landed
    ``succeeded`` + ``abstained=True`` with nothing to review — total loss
    dressed up as a legitimate abstention. So the payload is carried forward
    unchanged with the rejection reason attached on ``NORMALIZER_BLOCKERS_KEY``,
    the same channel the normalizer already uses for the blockers it detects
    without aborting; ``validate/pipeline`` lifts it into
    ``validation_summary["blockers"]``, so the candidate reaches review as a
    proposal that cannot be accepted, reason included. Carrying it beats merely
    counting it because a reviewer can then see *which* payload was rejected.

    The counts are part of the stage output — hence of the durable
    ``step_completed`` event — so loss is legible without diffing event blobs.
    """
    normalized: list[dict[str, Any]] = []
    blocked = 0
    for raw in state.raw_proposals:
        payload, blockers = normalize_payload(raw)
        if blockers:
            blocked += 1
            payload = {**payload, NORMALIZER_BLOCKERS_KEY: blockers}
        normalized.append(payload)
    state.normalized = normalized
    if blocked:
        emit("normalize_blocked", run_id=state.request.run_id, blocked=blocked)
    return {
        "normalized": normalized,
        "normalized_count": len(normalized),
        "blocked_count": blocked,
    }


__all__ = ["stage_normalize"]
