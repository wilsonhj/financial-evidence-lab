"""Proposal / conflict / run persistence (always ``needs_review``; no auto-approve)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.hashing import proposal_id_for
from fel_workers.extraction.persist_checkpoint import (
    PostgresCheckpointStore as PostgresCheckpointStore,
)
from fel_workers.extraction.persist_conflicts import persist_conflicts as _persist_conflicts
from fel_workers.extraction.persist_events import PostgresEventStore as PostgresEventStore
from fel_workers.extraction.persist_memory import MemoryPersistStore as MemoryPersistStore
from fel_workers.extraction.persist_reads import load_run_pins, load_span_pins
from fel_workers.extraction.persist_types import TERMINAL_RUN_STATUSES as TERMINAL_RUN_STATUSES
from fel_workers.extraction.persist_types import RunAlreadyTerminal as RunAlreadyTerminal
from fel_workers.extraction.persist_types import RunPins as RunPins
from fel_workers.extraction.persist_types import SpanPin as SpanPin
from fel_workers.extraction.persist_types import UsageSnapshot as UsageSnapshot
from fel_workers.extraction.persist_types import _ensure_needs_review as _ensure_needs_review
from fel_workers.extraction.types import ConflictDraft, ProposalDraft

__all__ = [
    "MemoryPersistStore",
    "PostgresCheckpointStore",
    "PostgresEventStore",
    "PostgresPersistStore",
    "RunAlreadyTerminal",
    "RunPins",
    "SpanPin",
    "TERMINAL_RUN_STATUSES",
    "UsageSnapshot",
    "assert_workspace_ownership",
]


def assert_workspace_ownership(
    conn: psycopg.Connection[Any], *, org_id: str, workspace_id: str
) -> None:
    """Service-role workers must confirm workspace belongs to org before writes."""
    row = conn.execute(
        "SELECT 1 FROM workspaces WHERE id = %s AND org_id = %s",
        (workspace_id, org_id),
    ).fetchone()
    if row is None:
        raise StepFailed(
            f"workspace {workspace_id} is not owned by org {org_id}",
            code="workspace_ownership",
        )


@dataclass
class PostgresPersistStore:
    """Tenant-scoped writes to migration 0004 extraction tables."""

    conn: psycopg.Connection[Any]

    def mark_running(self, *, run_id: str, org_id: str) -> None:
        """Promote ``queued`` to ``running`` (a no-op on a run already ``running``).

        A terminal row is refused with :class:`RunAlreadyTerminal` BEFORE the
        UPDATE is issued, so the caller gets a typed error it can dead-letter on
        rather than 0004's ``terminal extraction run cannot be mutated`` (#146).
        """
        status = self.load_run_status(run_id=run_id, org_id=org_id)
        if status is not None and status in TERMINAL_RUN_STATUSES:
            raise RunAlreadyTerminal(run_id=run_id, status=status)
        self.conn.execute(
            """
            UPDATE extraction_runs
               SET status = 'running', started_at = COALESCE(started_at, now())
             WHERE id = %s AND org_id = %s AND status IN ('queued', 'running')
            """,
            (run_id, org_id),
        )

    def set_run_status(
        self,
        *,
        run_id: str,
        org_id: str,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Write a new run status, or raise :class:`RunAlreadyTerminal`.

        Same pre-check as :meth:`mark_running`: a terminal row is refused with
        the typed error BEFORE the UPDATE, so the consumer never sees 0004's
        ``terminal extraction run cannot be mutated`` (#146).
        """
        current = self.load_run_status(run_id=run_id, org_id=org_id)
        if current is not None and current in TERMINAL_RUN_STATUSES:
            raise RunAlreadyTerminal(run_id=run_id, status=current)
        finished = status in {"succeeded", "failed", "cancelled"}
        self.conn.execute(
            """
            UPDATE extraction_runs
               SET status = %s,
                   error = %s::jsonb,
                   finished_at = CASE WHEN %s THEN now() ELSE finished_at END
             WHERE id = %s AND org_id = %s
            """,
            (status, json.dumps(error) if error else None, finished, run_id, org_id),
        )

    def record_usage(self, *, run_id: str, org_id: str, usage: UsageSnapshot) -> None:
        """Mirror accumulated usage onto the run row so a requeue resumes from it.

        Each counter is merged with ``GREATEST`` rather than assigned. These are
        cumulative-from-zero totals for the run, so they may only ever climb —
        and a blind ``SET`` let a writer holding a stale snapshot erase spend
        another writer had already recorded, which is reachable because
        ``lease_check`` fails open: a heartbeat thread that dies on a connection
        error leaves the old worker believing it still owns the job while the
        reaper hands it to a new one. Budget caps are only as good as the ledger
        they read, so an erased call is an unbounded run.

        ``GREATEST`` also puts the merge inside the statement, where Postgres
        resolves it under the row lock. Read-then-write in Python would leave the
        same race between the two statements.
        """
        self.conn.execute(
            """
            UPDATE extraction_runs
               SET calls_used = GREATEST(calls_used, %s),
                   input_tokens_used = GREATEST(input_tokens_used, %s),
                   output_tokens_used = GREATEST(output_tokens_used, %s),
                   cost_usd = GREATEST(cost_usd, %s)
             WHERE id = %s AND org_id = %s
            """,
            (
                usage.calls_used,
                usage.input_tokens_used,
                usage.output_tokens_used,
                usage.cost_usd,
                run_id,
                org_id,
            ),
        )

    def load_run_status(self, *, run_id: str, org_id: str) -> str | None:
        """The run row's current status, or ``None`` when there is no such row.

        Tenant-scoped like every other read here. Separate from
        :meth:`load_run_pins` because status is the one thing about a run that is
        NOT a pin: it is exactly the mutable field, and a caller that needs to
        know whether the run is still open must not have to load seventeen
        immutable ones to find out.
        """
        row = self.conn.execute(
            "SELECT status FROM extraction_runs WHERE id = %s AND org_id = %s",
            (run_id, org_id),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def load_run_pins(self, *, run_id: str, org_id: str) -> RunPins | None:
        return load_run_pins(self.conn, run_id=run_id, org_id=org_id)

    def load_span_pins(self, span_ids: list[str]) -> dict[str, SpanPin]:
        return load_span_pins(self.conn, span_ids)

    def load_usage(self, *, run_id: str, org_id: str) -> UsageSnapshot:
        """Usage spent by earlier attempts of this run."""
        row = self.conn.execute(
            """
            SELECT calls_used, input_tokens_used, output_tokens_used, cost_usd
              FROM extraction_runs
             WHERE id = %s AND org_id = %s
            """,
            (run_id, org_id),
        ).fetchone()
        if row is None:
            return UsageSnapshot()
        return UsageSnapshot(
            calls_used=row[0] or 0,
            input_tokens_used=row[1] or 0,
            output_tokens_used=row[2] or 0,
            cost_usd=Decimal(str(row[3] if row[3] is not None else 0)),
            wall_seconds_used=self._load_wall_seconds(run_id=run_id, org_id=org_id),
        )

    def _load_wall_seconds(self, *, run_id: str, org_id: str) -> float:
        """Frozen 0004 has no wall-clock column, so this counter rides the
        ``budget_updated`` event log instead of a row on ``extraction_runs`` —
        but ``BudgetState.elapsed_seconds()`` (``budget.py``) is cumulative from
        zero exactly like ``calls_used``/``input_tokens_used``/etc, so it is
        exposed to the identical stale-writer race ``record_usage`` guards
        against with ``GREATEST``: a worker whose heartbeat connection dies
        keeps running while the reaper hands its job to a second worker, both
        flush usage for the same run, and whichever flush lands LAST used to
        win regardless of size. ``ORDER BY id DESC LIMIT 1`` picked exactly that
        — the most recently appended event, not the largest value — so a slow
        worker's stale, smaller snapshot could erase a faster worker's larger
        one. ``MAX`` merges the same way ``GREATEST`` does for the four
        columns: read every event this run has appended, not just the last one.

        The ``~`` filter excludes any row whose ``wall_seconds_used`` is
        absent, JSON ``null``, or not a bare numeric literal, before the cast
        ever runs: ``'not-a-number'::float`` raises and would fail the whole
        query for every event of the run, and a key that is missing or JSON
        ``null`` makes ``payload->>'wall_seconds_used'`` SQL NULL, against
        which ``~`` itself evaluates to NULL — which WHERE treats as false, so
        those rows are dropped rather than erroring either way. One malformed
        or pre-this-field historical event must not take down every later
        attempt's usage read. ``MAX`` over zero matching rows still returns
        exactly one row with a NULL aggregate, not zero rows, so the
        ``row[0] is None`` guard below covers "no budget_updated event yet"
        and "every event's value was unusable" the same way it already covered
        "no event yet" before this change.
        """
        row = self.conn.execute(
            """
            SELECT MAX((payload->>'wall_seconds_used')::float)
              FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'budget_updated'
               AND payload->>'wall_seconds_used' ~ '^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$'
            """,
            (org_id, run_id),
        ).fetchone()
        if row is None or row[0] is None:
            return 0.0
        return float(row[0])

    def persist_proposals(
        self,
        *,
        run_id: str,
        org_id: str,
        workspace_id: str,
        drafts: list[ProposalDraft],
    ) -> list[ProposalDraft]:
        assert_workspace_ownership(self.conn, org_id=org_id, workspace_id=workspace_id)
        persisted: list[ProposalDraft] = []
        for draft in drafts:
            _ensure_needs_review(draft)
            pid = draft.id or proposal_id_for(
                run_id=run_id,
                kind=draft.kind,
                metric_id=draft.metric_id,
                raw_payload_hash=draft.raw_payload_hash,
            )
            draft.id = pid
            self.conn.execute(
                """
                INSERT INTO extraction_proposals (
                    id, org_id, workspace_id, run_id, kind, metric_id, payload,
                    raw_payload_hash, definition_hash, comparability_key,
                    record_confidence, field_confidences, validation_summary,
                    state, review_priority
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s::jsonb,
                    %s, %s::jsonb, %s::jsonb,
                    'needs_review', %s
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    pid,
                    org_id,
                    workspace_id,
                    run_id,
                    draft.kind,
                    draft.metric_id,
                    json.dumps(draft.payload),
                    draft.raw_payload_hash,
                    draft.definition_hash,
                    json.dumps(draft.comparability_key),
                    draft.record_confidence,
                    json.dumps(draft.field_confidences),
                    json.dumps(draft.validation_summary),
                    draft.review_priority,
                ),
            )
            for ordinal, row in enumerate(draft.evidence):
                span_id = row.get("source_span_id")
                if not span_id:
                    continue
                document_version_id = row.get("document_version_id")
                if not document_version_id:
                    # Fail closed: never substitute span_id (composite FK to source_spans).
                    raise StepFailed(
                        f"proposal evidence missing document_version_id for span {span_id}"
                    )
                self.conn.execute(
                    """
                    INSERT INTO extraction_proposal_evidence (
                        org_id, proposal_id, source_span_id, document_version_id,
                        role, citation_status, ordinal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        org_id,
                        pid,
                        span_id,
                        document_version_id,
                        row.get("role") or "supports",
                        row.get("citation_status") or "partial",
                        ordinal,
                    ),
                )
            persisted.append(draft)
        return persisted

    def persist_conflicts(
        self,
        *,
        org_id: str,
        workspace_id: str,
        drafts: list[ConflictDraft],
    ) -> list[ConflictDraft]:
        assert_workspace_ownership(self.conn, org_id=org_id, workspace_id=workspace_id)
        return _persist_conflicts(
            self.conn, org_id=org_id, workspace_id=workspace_id, drafts=drafts
        )

    def persist_outputs_atomic(
        self,
        *,
        run_id: str,
        org_id: str,
        workspace_id: str,
        proposals: list[ProposalDraft],
        conflicts: list[ConflictDraft],
        events: Any,
    ) -> tuple[list[ProposalDraft], list[ConflictDraft]]:
        """Commit proposals, their evidence and their conflicts in ONE transaction.

        The persist stage used to call ``persist_proposals`` and then
        ``persist_conflicts`` with nothing between them, on the worker's
        ``autocommit=True`` connection. Every statement was therefore its own
        transaction, so when the conflict write raised — 0004's
        ``conflict_terminal`` guard refusing to attach unreviewed proposals to an
        already-adjudicated group is the reachable trigger — the proposals and
        their evidence were already durable. Observed: 3 proposals and 3 evidence
        rows committed, conflict membership 0, run finalised ``failed``.

        The result is unrepairable, which is what makes this worth a transaction
        rather than a retry. ``fel_guard_extraction_proposal`` calls
        ``fel_assert_extraction_run_open`` on the UPDATE path, so once the run is
        terminal the orphans can no longer be moved to ``rejected``, and DELETE
        is forbidden outright. The only mechanically available repair is
        hand-inserting the missing conflict members — exactly what the
        ``conflict_terminal`` guard exists to prevent. Until then a reviewer sees
        proposals the pipeline had grouped as mutually contradictory, presented
        as independent findings, with no way to correct or withdraw them.

        ``conn.transaction()`` opens an explicit block even under autocommit, so
        either the whole stage lands or none of it does and the run simply fails
        with nothing written. This is the same fix, for the same reason, as
        :meth:`PostgresCheckpointStore.commit_succeeded_atomic`.

        The ``needs_review`` assertion runs INSIDE the block: an escaped proposal
        must roll back the write it escaped in, not merely be reported after it
        is durable.
        """
        with self.conn.transaction():
            persisted = self.persist_proposals(
                run_id=run_id, org_id=org_id, workspace_id=workspace_id, drafts=proposals
            )
            for draft in persisted:
                if draft.state != "needs_review":
                    # Typed exactly as the workflow stage that used to carry this
                    # check, so moving it here does not reclassify the failure.
                    raise StepFailed("proposal escaped needs_review — auto-approve forbidden")
            groups = self.persist_conflicts(
                org_id=org_id, workspace_id=workspace_id, drafts=conflicts
            )
            events.append(
                org_id=org_id,
                run_id=run_id,
                event_type="proposals_persisted",
                payload={"count": len(persisted), "conflicts": len(groups)},
            )
        return persisted, groups
