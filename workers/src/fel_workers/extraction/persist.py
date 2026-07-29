"""Proposal / conflict / run persistence (always ``needs_review``; no auto-approve)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg

from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.events import ExtractionEvent, MemoryEventStore, redact_payload
from fel_workers.extraction.hashing import proposal_id_for
from fel_workers.extraction.types import ConflictDraft, ProposalDraft, StageRecord

__all__ = [
    "MemoryPersistStore",
    "PostgresCheckpointStore",
    "PostgresEventStore",
    "PostgresPersistStore",
    "UsageSnapshot",
    "assert_workspace_ownership",
]


@dataclass(frozen=True)
class UsageSnapshot:
    """Accumulated run usage, carried across queue attempts of the same run."""

    calls_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    cost_usd: Decimal = Decimal("0")
    wall_seconds_used: float = 0.0


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


def _ensure_needs_review(draft: ProposalDraft) -> None:
    """M3 invariant: proposals enter review only — never auto-approve."""
    if draft.state != "needs_review":
        raise ValueError("M3 proposals must enter needs_review; no auto-approve")


@dataclass
class MemoryPersistStore:
    """Idempotent in-memory proposal/conflict store for tests and mock E2E."""

    proposals: dict[str, ProposalDraft] = field(default_factory=dict)
    conflicts: dict[str, ConflictDraft] = field(default_factory=dict)
    run_status: dict[str, str] = field(default_factory=dict)
    usage: dict[str, UsageSnapshot] = field(default_factory=dict)

    def persist_proposals(
        self,
        *,
        run_id: str,
        org_id: str,
        workspace_id: str,
        drafts: list[ProposalDraft],
    ) -> list[ProposalDraft]:
        del org_id, workspace_id
        persisted: list[ProposalDraft] = []
        for draft in drafts:
            _ensure_needs_review(draft)
            pid = draft.id or proposal_id_for(
                run_id=run_id,
                kind=draft.kind,
                metric_id=draft.metric_id,
                raw_payload_hash=draft.raw_payload_hash,
            )
            if pid in self.proposals:
                persisted.append(self.proposals[pid])
                continue
            draft.id = pid
            self.proposals[pid] = draft
            persisted.append(draft)
        return persisted

    def persist_conflicts(
        self,
        *,
        org_id: str,
        workspace_id: str,
        drafts: list[ConflictDraft],
    ) -> list[ConflictDraft]:
        del org_id, workspace_id
        out: list[ConflictDraft] = []
        for draft in drafts:
            if len(draft.member_proposal_ids) < 2:
                raise ValueError("conflict groups require at least two members")
            existing = self.conflicts.get(draft.conflict_key)
            if existing is not None:
                out.append(existing)
                continue
            draft.id = draft.id or draft.conflict_key
            self.conflicts[draft.conflict_key] = draft
            out.append(draft)
        return out

    def set_run_status(
        self,
        *,
        run_id: str,
        org_id: str,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        del org_id, error
        self.run_status[run_id] = status

    def record_usage(self, *, run_id: str, org_id: str, usage: UsageSnapshot) -> None:
        del org_id
        self.usage[run_id] = usage

    def load_usage(self, *, run_id: str, org_id: str) -> UsageSnapshot:
        del org_id
        return self.usage.get(run_id, UsageSnapshot())

    def mark_running(self, *, run_id: str, org_id: str) -> None:
        del org_id
        self.run_status[run_id] = "running"


@dataclass
class PostgresPersistStore:
    """Tenant-scoped writes to migration 0004 extraction tables."""

    conn: psycopg.Connection[Any]

    def mark_running(self, *, run_id: str, org_id: str) -> None:
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
        """Mirror accumulated usage onto the run row so a requeue resumes from it."""
        self.conn.execute(
            """
            UPDATE extraction_runs
               SET calls_used = %s,
                   input_tokens_used = %s,
                   output_tokens_used = %s,
                   cost_usd = %s
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
        """Frozen 0004 has no wall-clock column; it rides the budget_updated event."""
        row = self.conn.execute(
            """
            SELECT payload->>'wall_seconds_used'
              FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'budget_updated'
             ORDER BY id DESC
             LIMIT 1
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
        out: list[ConflictDraft] = []
        for draft in drafts:
            if len(draft.member_proposal_ids) < 2:
                raise ValueError("conflict groups require at least two members")
            cid = draft.id or str(uuid.uuid4())
            self.conn.execute(
                """
                INSERT INTO extraction_conflicts (
                    id, org_id, workspace_id, conflict_key, reason_codes, status
                ) VALUES (%s, %s, %s, %s, %s, 'open')
                ON CONFLICT (org_id, workspace_id, conflict_key) DO NOTHING
                """,
                (cid, org_id, workspace_id, draft.conflict_key, draft.reason_codes),
            )
            # ON CONFLICT DO NOTHING may skip insert — resolve the real row id
            # before writing members (members require org_id + conflict_id).
            row = self.conn.execute(
                """
                SELECT id FROM extraction_conflicts
                 WHERE org_id = %s AND workspace_id = %s AND conflict_key = %s
                """,
                (org_id, workspace_id, draft.conflict_key),
            ).fetchone()
            if row is None:
                raise StepFailed(
                    f"conflict row missing after upsert for key {draft.conflict_key}",
                    code="conflict_upsert",
                )
            real_cid = str(row[0])
            draft.id = real_cid
            for proposal_id in draft.member_proposal_ids:
                self.conn.execute(
                    """
                    INSERT INTO extraction_conflict_members
                        (conflict_id, proposal_id, org_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (real_cid, proposal_id, org_id),
                )
            out.append(draft)
        return out


@dataclass
class PostgresCheckpointStore:
    conn: psycopg.Connection[Any]
    _memory: MemoryCheckpointStore = field(default_factory=MemoryCheckpointStore)

    def load_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        step_name: str,
        input_hash: str,
        workflow_version: str,
    ) -> StageRecord | None:
        mem = self._memory.load_succeeded(
            run_id=run_id,
            org_id=org_id,
            step_name=step_name,
            input_hash=input_hash,
            workflow_version=workflow_version,
        )
        if mem is not None:
            return mem
        row = self.conn.execute(
            """
            SELECT step_name, attempt, status, input_hash, output_hash,
                   provider_response_id, input_tokens, output_tokens, cost_usd, error
              FROM extraction_run_steps
             WHERE run_id = %s AND org_id = %s AND step_name = %s AND input_hash = %s
               AND workflow_version = %s AND status = 'succeeded'
             LIMIT 1
            """,
            (run_id, org_id, step_name, input_hash, workflow_version),
        ).fetchone()
        if row is None:
            return None
        output = self._load_stage_output(
            org_id=org_id,
            run_id=run_id,
            step_name=step_name,
            input_hash=input_hash,
        )
        return StageRecord(
            step_name=row[0],
            attempt=row[1],
            status=row[2],
            input_hash=row[3],
            output_hash=row[4],
            provider_response_id=row[5],
            input_tokens=row[6] or 0,
            output_tokens=row[7] or 0,
            cost_usd=Decimal(str(row[8] if row[8] is not None else 0)),
            error=row[9],
            output=output,
        )

    def _load_stage_output(
        self,
        *,
        org_id: str,
        run_id: str,
        step_name: str,
        input_hash: str,
    ) -> Any:
        """Hydrate stage output from step_completed events (no steps.output column)."""
        row = self.conn.execute(
            """
            SELECT payload
              FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'step_completed'
               AND payload->>'step_name' = %s
               AND payload->>'input_hash' = %s
             ORDER BY id DESC
             LIMIT 1
            """,
            (org_id, run_id, step_name, input_hash),
        ).fetchone()
        if row is None:
            return None
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None
        return payload.get("stage_output")

    def commit_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord:
        self._insert_step_row(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
        )
        return self._memory.commit_succeeded(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
        )

    def _insert_step_row(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> None:
        step_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO extraction_run_steps (
                id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
                workflow_version, schema_version, prompt_version, provider_response_id,
                input_tokens, output_tokens, cost_usd, started_at, finished_at
            ) VALUES (
                %s, %s, %s, %s, %s, 'succeeded', %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, now(), now()
            )
            ON CONFLICT DO NOTHING
            """,
            (
                step_id,
                org_id,
                run_id,
                record.step_name,
                record.attempt,
                record.input_hash,
                record.output_hash,
                workflow_version,
                "extraction-payload/v1",
                "prompts/v1",
                record.provider_response_id,
                record.input_tokens,
                record.output_tokens,
                record.cost_usd,
            ),
        )

    def commit_succeeded_atomic(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
        events: Any,
        event_payload: dict[str, Any],
    ) -> StageRecord:
        """Commit the step row and its ``step_completed`` event in ONE transaction.

        The event payload's ``stage_output`` is the only carrier of a stage's
        result (0004 has no ``steps.output`` column). Under the worker's
        ``autocommit=True`` connection the two writes were separate transactions,
        so a crash in between left a durably ``succeeded`` step with a non-null
        ``output_hash`` and no recoverable output. On resume ``load_succeeded``
        returned ``output=None``, ``_restore_output`` bailed out, the stage was
        skipped with zero model calls, and the run landed ``succeeded`` +
        ``abstained=True`` with no proposals — silent data loss reported as a
        legitimate abstention, made permanent by 0004's terminal-run guard.

        ``conn.transaction()`` opens an explicit block even in autocommit mode, so
        either both rows land or neither does and the stage simply re-runs. The
        in-process cache is only populated after the block commits, so a rollback
        cannot leave ``load_succeeded`` answering from memory for a step whose row
        no longer exists.
        """
        with self.conn.transaction():
            self._insert_step_row(
                run_id=run_id,
                org_id=org_id,
                workflow_version=workflow_version,
                record=record,
            )
            events.append(
                org_id=org_id,
                run_id=run_id,
                event_type="step_completed",
                payload=event_payload,
            )
        return self._memory.commit_succeeded(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
        )


@dataclass
class PostgresEventStore:
    conn: psycopg.Connection[Any]
    _memory: MemoryEventStore = field(default_factory=MemoryEventStore)

    def append(
        self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> ExtractionEvent:
        event = self._memory.append(
            org_id=org_id, run_id=run_id, event_type=event_type, payload=payload
        )
        self.conn.execute(
            """
            INSERT INTO extraction_run_events (org_id, run_id, event_type, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (org_id, run_id, event_type, json.dumps(redact_payload(payload))),
        )
        return event
