"""Agentic extraction workers (M3-EXTRACTION-CORE).

Operator notes (M3-107):
- Enqueue jobs with ``kind=extraction_run`` on queue ``extraction``.
- Bind ``MockStructuredLLMProvider`` for CI/mock smoke; never log source text.
- Successful proposal persistence leaves runs in ``waiting_review``.
- Provider/schema/budget failures leave runs ``failed`` with typed error codes.
"""

from __future__ import annotations

from fel_workers.extraction.handler import (
    DEFAULT_EXTRACTION_QUEUE,
    JOB_KIND_EXTRACTION_RUN,
    handle_extraction_run,
)
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

__all__ = [
    "DEFAULT_EXTRACTION_QUEUE",
    "JOB_KIND_EXTRACTION_RUN",
    "WorkflowDeps",
    "handle_extraction_run",
    "run_extraction_workflow",
]
