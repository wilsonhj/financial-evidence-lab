"""``verify_citations`` — grade every citation row against the pinned evidence."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.stages.io import evidence_map
from fel_workers.extraction.types import WorkflowState
from fel_workers.extraction.validate.pipeline import citation_status_for


def stage_verify_citations(state: WorkflowState) -> dict[str, Any]:
    """Grade every citation row from the pinned evidence, overwriting the row.

    The grade is assigned, never defaulted: `setdefault` let a model-supplied
    `citation_status: "verified"` survive into `extraction_proposal_evidence`,
    which 0004 makes append-only — UPDATE and DELETE both raise — so the wrong
    value could never be corrected. `citation_status_for` is the single rule (see
    its docstring for why span membership alone earns `partial`, not `verified`).
    """
    pinned = dict(evidence_map(state.evidence))
    counts = {"verified": 0, "partial": 0, "invalid": 0}
    for draft in state.validated:
        for row in draft.evidence:
            status = citation_status_for(row, evidence_by_span=pinned)
            row["citation_status"] = status
            counts[status] += 1
    return {
        "invalid_citations": counts["invalid"],
        "partial_citations": counts["partial"],
        "verified_citations": counts["verified"],
        "checked": len(state.validated),
    }


__all__ = ["stage_verify_citations"]
