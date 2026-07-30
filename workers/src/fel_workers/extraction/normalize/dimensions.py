"""Dimension map normalization."""

from __future__ import annotations

from typing import Any


def normalize_dimensions(dimensions: Any) -> tuple[dict[str, str], list[str]]:
    blockers: list[str] = []
    if dimensions is None:
        return {}, []
    if not isinstance(dimensions, dict):
        return {}, ["dimensions_invalid_type"]
    out: dict[str, str] = {}
    for key, value in sorted(dimensions.items(), key=lambda kv: str(kv[0])):
        if not isinstance(key, str) or not isinstance(value, str):
            blockers.append("dimensions_non_string")
            continue
        out[key] = value
    return out, blockers


__all__ = ["normalize_dimensions"]
