"""Duplicate detection via comparability keys."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fel_workers.extraction.hashing import canonical_json, hash_json


def comparability_key_for(payload: dict[str, Any]) -> dict[str, Any]:
    """Stable local comparability fingerprint for duplicate grouping.

    Full ontology-keyed strings are applied in ``validate.pipeline`` when
    building proposal drafts; this helper only needs a deterministic dict
    for hashing duplicate clusters.
    """
    return {
        "metric_id": payload.get("metric_id"),
        "entity_id": payload.get("entity_id"),
        "period": payload.get("period"),
        "unit": payload.get("unit"),
        "currency": payload.get("currency"),
        "dimensions": payload.get("dimensions") or {},
        "qualifiers": payload.get("qualifiers") or {},
    }


def find_duplicates(
    payloads: list[dict[str, Any]],
) -> list[tuple[str, list[int]]]:
    """Return (conflict_key, member_indexes) for duplicate comparability keys."""
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, payload in enumerate(payloads):
        key = hash_json(comparability_key_for(payload))
        groups[key].append(idx)
    return [(k, idxs) for k, idxs in groups.items() if len(idxs) >= 2]


def definition_hash_for(payload: dict[str, Any]) -> str:
    definition = payload.get("definition")
    return hash_json({"definition": definition, "metric_id": payload.get("metric_id")})


__all__ = [
    "comparability_key_for",
    "definition_hash_for",
    "find_duplicates",
    "canonical_json",
]
