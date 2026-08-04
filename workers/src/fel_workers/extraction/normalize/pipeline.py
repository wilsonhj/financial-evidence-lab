"""Normalization pipeline: Decimal-only; keep raw_value; no FX conversion."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.normalize.payload import normalize_payload as _normalize_one

__all__ = ["normalize_payload"]


def normalize_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return (normalized_payload, blockers). Always preserves raw_value.

    The blocker list carries only a *rejection* — a payload the normalizer could
    not normalize at all, returned unchanged so ``workflow._stage_normalize``
    can count it and carry it to review. Blockers the normalizer detects without
    aborting (a contradicted sign, an out-of-range scale, a monetary figure with
    no currency, a non-string dimension) ride inside the payload on
    ``NORMALIZER_BLOCKERS_KEY`` instead, which is what survives a checkpointed
    crash-resume; ``validate/pipeline.py`` lifts both into
    ``validation_summary["blockers"]``.
    """
    try:
        return _normalize_one(payload), []
    except ValueError as exc:
        return dict(payload), [str(exc)]
