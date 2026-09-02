"""``validate`` — schema, ontology and identity checks over the normalized payloads."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.context import ExecCtx
from fel_workers.extraction.stages.io import evidence_map
from fel_workers.extraction.validate import validate_proposals


def stage_validate(ctx: ExecCtx) -> dict[str, Any]:
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


__all__ = ["stage_validate"]
