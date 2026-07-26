"""Deterministic extraction-level conflict groups."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.types import ConflictDraft
from fel_workers.extraction.validate.duplicates import comparability_key_for, find_duplicates


def detect_conflicts(
    *,
    payloads: list[dict[str, Any]],
    proposal_ids: list[str],
) -> list[ConflictDraft]:
    """Build conflict drafts for duplicates and conflicting numeric values."""
    drafts: list[ConflictDraft] = []
    for key, idxs in find_duplicates(payloads):
        member_ids = [proposal_ids[i] for i in idxs]
        drafts.append(
            ConflictDraft(
                conflict_key=f"dup:{key}",
                reason_codes=["duplicate_comparability_key"],
                member_proposal_ids=member_ids,
            )
        )

    # Conflicting values under same metric/period/entity but different definitions.
    by_metric_period: dict[str, list[int]] = {}
    for idx, payload in enumerate(payloads):
        bucket = hash_json(
            {
                "entity_id": payload.get("entity_id"),
                "metric_id": payload.get("metric_id"),
                "period": payload.get("period"),
            }
        )
        by_metric_period.setdefault(bucket, []).append(idx)
    for bucket, idxs in by_metric_period.items():
        if len(idxs) < 2:
            continue
        values: list[str] = []
        defs: list[str] = []
        for i in idxs:
            p = payloads[i]
            raw = p.get("value") or p.get("low") or p.get("high") or p.get("raw_value")
            values.append(str(raw))
            defs.append(str(p.get("definition")))
        if len(set(values)) > 1 or len(set(defs)) > 1:
            # Skip if already covered as exact duplicate key.
            keys = {hash_json(comparability_key_for(payloads[i])) for i in idxs}
            if len(keys) == 1:
                continue
            drafts.append(
                ConflictDraft(
                    conflict_key=f"value:{bucket}",
                    reason_codes=["conflicting_values_or_definitions"],
                    member_proposal_ids=[proposal_ids[i] for i in idxs],
                )
            )
    return drafts


__all__ = ["detect_conflicts"]
