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
class MemoryPersistStore:
    """Idempotent in-memory proposal/conflict store for tests and mock E2E."""

    proposals: dict[str, ProposalDraft] = field(default_factory=dict)
    conflicts: dict[str, ConflictDraft] = field(default_factory=dict)
    run_status: dict[str, str] = field(default_factory=dict)

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
            if draft.state != "needs_review":
                raise ValueError("M3 proposals must enter needs_review; no auto-approve")
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
        self, *, run_id: str, status: str, error: dict[str, Any] | None = None
    ) -> None:
        del error
        self.run_status[run_id] = status

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
        self, *, run_id: str, status: str, error: dict[str, Any] | None = None
    ) -> None:
        finished = status in {"succeeded", "failed", "cancelled"}
        self.conn.execute(
            """
            UPDATE extraction_runs
               SET status = %s,
                   error = %s::jsonb,
                   finished_at = CASE WHEN %s THEN now() ELSE finished_at END
             WHERE id = %s
            """,
            (status, json.dumps(error) if error else None, finished, run_id),
        )

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
            if draft.state != "needs_review":
                raise ValueError("M3 proposals must enter needs_review; no auto-approve")
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
                        row.get("document_version_id") or span_id,
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
            draft.id = cid
            self.conn.execute(
                """
                INSERT INTO extraction_conflicts (
                    id, org_id, workspace_id, conflict_key, reason_codes, status
                ) VALUES (%s, %s, %s, %s, %s, 'open')
                ON CONFLICT (org_id, workspace_id, conflict_key) DO NOTHING
                """,
                (cid, org_id, workspace_id, draft.conflict_key, draft.reason_codes),
            )
            for proposal_id in draft.member_proposal_ids:
                self.conn.execute(
                    """
                    INSERT INTO extraction_conflict_members (conflict_id, proposal_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (cid, proposal_id),
                )
            out.append(draft)
        return out


@dataclass
class PostgresCheckpointStore:
    conn: psycopg.Connection[Any]
    _memory: MemoryCheckpointStore = field(default_factory=MemoryCheckpointStore)

    def load_succeeded(
        self, *, run_id: str, step_name: str, input_hash: str, workflow_version: str
    ) -> StageRecord | None:
        mem = self._memory.load_succeeded(
            run_id=run_id,
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
             WHERE run_id = %s AND step_name = %s AND input_hash = %s
               AND workflow_version = %s AND status = 'succeeded'
             LIMIT 1
            """,
            (run_id, step_name, input_hash, workflow_version),
        ).fetchone()
        if row is None:
            return None
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
        )

    def commit_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord:
        committed = self._memory.commit_succeeded(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
        )
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
        return committed


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
