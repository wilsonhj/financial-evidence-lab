"""Extraction validate stage."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.workflow_codec import evidence_map
from fel_workers.extraction.workflow_context import _ExecCtx


def _stage_validate(ctx: _ExecCtx) -> dict[str, Any]:
    state = ctx.state
    result = validate_proposals(
        run_id=state.request.run_id,
        payloads=state.normalized,
        evidence_by_span=dict(evidence_map(state.evidence)),
        ontology=ctx.ontology,
    )
    state.validated = result.proposals
    state.conflicts = result.conflicts
    return {
        "normalized": state.normalized,
        "proposal_count": len(result.proposals),
        "conflict_count": len(result.conflicts),
    }
