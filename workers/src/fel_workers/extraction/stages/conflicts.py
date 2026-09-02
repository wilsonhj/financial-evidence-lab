"""``detect_conflicts`` — re-export the conflicts ``validate`` already computed."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.types import WorkflowState


def stage_detect_conflicts(state: WorkflowState) -> dict[str, Any]:
    # Conflicts already computed in validate; re-export deterministically.
    return {
        "conflict_keys": [c.conflict_key for c in state.conflicts],
        "count": len(state.conflicts),
    }


__all__ = ["stage_detect_conflicts"]
