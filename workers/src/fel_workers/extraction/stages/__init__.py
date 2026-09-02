"""Stage bodies for the extraction workflow FSM.

``workflow.py`` owns the control loop — fencing, checkpoint lookup, commit,
failure recording and terminal handling — and dispatches into exactly one of
these functions per ``STAGE_ORDER`` step. A stage body may read and mutate
``WorkflowState``; it never writes a step row, appends an event or decides what
happens next.

``io`` holds the payload shaping on both sides of a stage: the value that is
hashed into the checkpoint key, and the restore that puts a checkpointed output
back into state on resume.
"""

from __future__ import annotations

from fel_workers.extraction.stages.citations import stage_verify_citations
from fel_workers.extraction.stages.conflicts import stage_detect_conflicts
from fel_workers.extraction.stages.evidence import stage_assemble_evidence
from fel_workers.extraction.stages.io import (
    evidence_map,
    restore_output,
    stage_input_payload,
)
from fel_workers.extraction.stages.model import stage_model
from fel_workers.extraction.stages.normalize import stage_normalize
from fel_workers.extraction.stages.persist import stage_persist
from fel_workers.extraction.stages.request import stage_validate_request
from fel_workers.extraction.stages.validate import stage_validate

__all__ = [
    "evidence_map",
    "restore_output",
    "stage_assemble_evidence",
    "stage_detect_conflicts",
    "stage_input_payload",
    "stage_model",
    "stage_normalize",
    "stage_persist",
    "stage_validate",
    "stage_validate_request",
    "stage_verify_citations",
]
