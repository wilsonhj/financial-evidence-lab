"""Extraction types persistence definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fel_workers.extraction.errors import ExtractionError
from fel_workers.extraction.types import ProposalDraft


@dataclass(frozen=True)
class UsageSnapshot:
    """Accumulated run usage, carried across queue attempts of the same run."""

    calls_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    cost_usd: Decimal = Decimal("0")
    wall_seconds_used: float = 0.0


@dataclass(frozen=True)
class RunPins:
    """The immutable identity 0004 records for a run, read back from the row.

    Every field here is protected by ``fel_guard_extraction_run``, which raises
    ``extraction run identity pins are immutable`` on any UPDATE that changes
    one. That makes the row — not the queue payload — the authority on what the
    run is: its cutoff, its corpus, its model and its budget ceilings. The
    package used to read ``extraction_runs`` exactly once (``load_usage``, four
    usage counters) and never compare a pin, so the budget CHECKs 0004 spends
    two constraints expressing were unenforceable at runtime: nothing read the
    columns that carry them.
    """

    workspace_id: str
    entity_id: str
    modes: tuple[str, ...]
    as_of: datetime
    corpus_version_id: str
    ontology_version: str
    workflow_version: str
    provider: str
    model: str
    policy_id: str
    input_manifest: dict[str, Any]
    input_hash: str
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: Decimal
    max_wall_seconds: int


@dataclass(frozen=True)
class SpanPin:
    """The canonical ``source_spans`` row behind one cited span.

    ``text_hash`` is the citation's content address, fixed at ingest against the
    document version's canonical text. It is the only value that can decide
    whether supplied evidence text really is what the span addresses; a hash
    computed from that same text answers a different question (is this text
    self-consistent) and always says yes.
    """

    source_span_id: str
    document_version_id: str
    text_hash: str


def _ensure_needs_review(draft: ProposalDraft) -> None:
    """M3 invariant: proposals enter review only — never auto-approve."""
    if draft.state != "needs_review":
        raise ValueError("M3 proposals must enter needs_review; no auto-approve")


TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
"""Run statuses frozen 0004's ``fel_guard_extraction_run`` refuses to mutate."""


class RunAlreadyTerminal(ExtractionError):
    """A write was refused because the run is already terminal (#146).

    Python twin of 0004's ``terminal extraction run cannot be mutated``, raised
    by BOTH persist stores before any write, so the consumer can dead-letter the
    job instead of retrying it against a row that can never reopen — and so the
    defect cannot hide behind a more permissive in-memory double again.
    """

    code = "run_terminal"

    def __init__(self, *, run_id: str, status: str) -> None:
        super().__init__(f"extraction run {run_id} is already {status}: terminal runs are final")
        self.run_id = run_id
        self.status = status
