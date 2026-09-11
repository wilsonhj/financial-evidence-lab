"""Extraction detect conflicts stage."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.types import (
    WorkflowState,
)


def _stage_detect_conflicts(state: WorkflowState) -> dict[str, Any]:
    # Conflicts already computed in validate; re-export deterministically.
    return {
        "conflict_keys": [c.conflict_key for c in state.conflicts],
        "count": len(state.conflicts),
    }
