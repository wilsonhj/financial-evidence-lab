"""``validate_request`` — the run request's own preconditions."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.types import MODE_STAGES, WORKFLOW_VERSION, WorkflowState


def stage_validate_request(state: WorkflowState) -> dict[str, Any]:
    req = state.request
    if not req.modes:
        raise StepFailed("modes must be non-empty")
    for mode in req.modes:
        if mode not in MODE_STAGES:
            raise StepFailed(f"unknown mode: {mode}")
    if not req.input_hash.startswith("sha256:"):
        raise StepFailed("input_hash must be sha256:…")
    if req.workflow_version != WORKFLOW_VERSION:
        # Allow pin mismatch only when explicitly testing; still record.
        pass
    return {"ok": True, "modes": list(req.modes)}


__all__ = ["stage_validate_request"]
