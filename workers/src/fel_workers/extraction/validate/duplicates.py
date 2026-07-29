"""Duplicate detection via fingerprints and comparability keys."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fel_workers.extraction.hashing import canonical_json, hash_json


def duplicate_groups(payloads: list[dict[str, Any]]) -> list[list[int]]:
    """Group indices that share kind+metric_id+period+currency+value fingerprint.

    Currency scopes the fingerprint (as it does in ``comparability_key_for``):
    the same number reported in USD and in JPY is two figures, not one restated
    twice, and must not carry a ``duplicate_candidate`` blocker.
    """
    buckets: dict[str, list[int]] = {}
    for idx, payload in enumerate(payloads):
        key = hash_json(
            {
                "kind": payload.get("kind"),
                "metric_id": payload.get("metric_id"),
                "period": payload.get("period"),
                "currency": payload.get("currency"),
                "value": payload.get("value"),
                "low": payload.get("low"),
                "high": payload.get("high"),
                "category": payload.get("category"),
            }
        )
        buckets.setdefault(key, []).append(idx)
    return [members for members in buckets.values() if len(members) > 1]


def conflict_key_for(
    payload: dict[str, Any],
    *,
    ontology_comparability_key: str | None = None,
) -> str:
    """Deterministic conflict grouping key.

    Prefer the ontology comparability key (e.g. NRR ``base_quantity``) when
    present so non-comparable definitions never share a value_disagreement
    bucket. Fall back to payload shape including qualifiers.
    """
    if ontology_comparability_key:
        return hash_json(
            {
                "comparability": ontology_comparability_key,
                "kind": payload.get("kind"),
                "entity_id": payload.get("entity_id"),
                "period": payload.get("period"),
            }
        )
    # Careful fallback: include qualifiers so distinct NRR bases do not collide
    # when ontology key construction failed closed.
    return hash_json(
        {
            "kind": payload.get("kind"),
            "metric_id": payload.get("metric_id"),
            "entity_id": payload.get("entity_id"),
            "period": payload.get("period"),
            "dimensions": payload.get("dimensions") or {},
            "qualifiers": payload.get("qualifiers") or {},
        }
    )


def value_fingerprint(payload: dict[str, Any]) -> str:
    return hash_json(
        {
            "value": payload.get("value"),
            "low": payload.get("low"),
            "high": payload.get("high"),
            "text": payload.get("text"),
            "category": payload.get("category"),
            "direction": payload.get("direction"),
            "raw_value": payload.get("raw_value"),
        }
    )


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
    "canonical_json",
    "comparability_key_for",
    "conflict_key_for",
    "definition_hash_for",
    "duplicate_groups",
    "find_duplicates",
    "value_fingerprint",
]
