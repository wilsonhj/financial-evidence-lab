"""Normalization pipeline: Decimal-only; keep raw_value; no FX conversion."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.normalize.payload import normalize_payload as _normalize_one

__all__ = ["normalize_payload", "normalize_proposals"]


def normalize_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return (normalized_payload, blockers). Always preserves raw_value."""
    try:
        return _normalize_one(payload), []
    except ValueError as exc:
        return dict(payload), [str(exc)]


def normalize_proposals(
    payloads: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[str]]]:
    return [normalize_payload(p) for p in payloads]
