"""Exact cosine oracle for HNSW recall verification (ADR-0006 clause 6).

Exact vector search is the recall oracle: a pure-Python brute-force cosine scan
over the staged vectors that the DB's approximate HNSW query is graded against.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """1 - cosine similarity; matches pgvector's ``<=>`` halfvec operator."""
    if len(a) != len(b):
        raise ValueError("vectors must share dimensionality")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def exact_knn(
    query: Sequence[float],
    items: Sequence[tuple[str, Sequence[float]]],
    k: int,
) -> list[str]:
    """Return the ids of the ``k`` nearest items by cosine distance.

    Ties break on id so the oracle is deterministic regardless of input order.
    """
    scored = [(cosine_distance(query, vector), item_id) for item_id, vector in items]
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return [item_id for _, item_id in scored[:k]]


def recall_at_k(exact_ids: Sequence[str], approx_ids: Sequence[str], k: int) -> float:
    """Fraction of the exact top-k also present in the approximate top-k."""
    if k <= 0:
        raise ValueError("k must be positive")
    gold = set(exact_ids[:k])
    if not gold:
        return 1.0
    found = gold.intersection(approx_ids[:k])
    return len(found) / len(gold)
