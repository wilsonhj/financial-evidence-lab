"""Proposal / conflict / run persistence (always ``needs_review``; no auto-approve)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.events import (
    ExtractionEvent,
    MemoryEventStore,
    redact_event_payload,
)
from fel_workers.extraction.hashing import proposal_id_for
from fel_workers.extraction.types import ConflictDraft, ProposalDraft, StageRecord

__all__ = [
    "MemoryPersistStore",
    "PostgresCheckpointStore",
    "PostgresEventStore",
    "PostgresPersistStore",
    "RunPins",
    "SpanPin",
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
        """Memory-path twin of the Postgres combined write (no transaction needed)."""
        persisted = self.persist_proposals(
            run_id=run_id, org_id=org_id, workspace_id=workspace_id, drafts=proposals
        )
        for draft in persisted:
            if draft.state != "needs_review":
                raise StepFailed("proposal escaped needs_review — auto-approve forbidden")
        groups = self.persist_conflicts(org_id=org_id, workspace_id=workspace_id, drafts=conflicts)
        events.append(
            org_id=org_id,
            run_id=run_id,
            event_type="proposals_persisted",
            payload={"count": len(persisted), "conflicts": len(groups)},
        )
        return persisted, groups

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

    def load_run_status(self, *, run_id: str, org_id: str) -> str | None:
        del org_id
        return self.run_status.get(run_id)


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
        """Read the run's immutable identity back, or ``None`` if there is no row.

        Tenant-scoped by ``org_id`` like every other read here, so a payload
        cannot reach another org's run row to bind against.
        """
        row = self.conn.execute(
            """
            SELECT workspace_id, entity_id, modes, as_of, corpus_version_id,
                   ontology_version, workflow_version, provider, model, policy_id,
                   input_manifest, input_hash, max_calls, max_input_tokens,
                   max_output_tokens, max_cost_usd, max_wall_seconds
              FROM extraction_runs
             WHERE id = %s AND org_id = %s
            """,
            (run_id, org_id),
        ).fetchone()
        if row is None:
            return None
        manifest = row[10]
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        return RunPins(
            workspace_id=str(row[0]),
            entity_id=str(row[1]),
            modes=tuple(str(mode) for mode in row[2]),
            as_of=row[3],
            corpus_version_id=str(row[4]),
            ontology_version=str(row[5]),
            workflow_version=str(row[6]),
            provider=str(row[7]),
            model=str(row[8]),
            policy_id=str(row[9]),
            input_manifest=dict(manifest or {}),
            input_hash=str(row[11]),
            max_calls=int(row[12]),
            max_input_tokens=int(row[13]),
            max_output_tokens=int(row[14]),
            max_cost_usd=Decimal(str(row[15])),
            max_wall_seconds=int(row[16]),
        )

    def load_span_pins(self, span_ids: list[str]) -> dict[str, SpanPin]:
        """Canonical ``source_spans`` rows for the cited spans, keyed by span id.

        Spans are corpus-global (no ``org_id`` column in 0002); tenancy on the
        evidence path is carried by ``extraction_proposal_evidence``'s composite
        FK and by the run's own workspace bind, not here.

        Ids that are not well-formed UUIDs are simply absent from the result
        rather than raising: the caller fails them closed as unresolvable spans,
        which is the same outcome with a message that names the span.
        """
        wanted: list[str] = []
        for span_id in span_ids:
            try:
                wanted.append(str(uuid.UUID(span_id)))
            except ValueError:
                continue
        if not wanted:
            return {}
        rows = self.conn.execute(
            """
            SELECT id, document_version_id, text_hash
              FROM source_spans
             WHERE id = ANY(%s::uuid[])
            """,
            (wanted,),
        ).fetchall()
        return {
            str(row[0]): SpanPin(
                source_span_id=str(row[0]),
                document_version_id=str(row[1]),
                text_hash=str(row[2]),
            )
            for row in rows
        }

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
                SELECT id, status FROM extraction_conflicts
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
            existing_status = str(row[1])
            if existing_status != "open":
                # conflict_key carries no run scope, so a rerun of the same
                # disagreement resolves to the EARLIER row. Attaching this run's
                # unreviewed proposals would silently reuse a human's
                # adjudication, and 0004 forbids DELETE on extraction_conflicts
                # and grants no DELETE on its members — the record could never be
                # unwritten. Reopening is possible but the status CHECK would
                # force clearing resolved_by/resolved_at, destroying the audit of
                # who adjudicated it. Fail closed until the identity scope is
                # decided (needs contract-change + ADR).
                raise StepFailed(
                    f"conflict {draft.conflict_key} already exists as "
                    f"{existing_status!r}; refusing to attach unreviewed proposals "
                    "to an adjudicated group",
                    code="conflict_terminal",
                )
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
        # `output` comes off the step row itself (migration 0006 / ADR-0011). It
        # used to be scanned out of the `step_completed` event payload, which is
        # why that payload had to carry verbatim filing text and why the event
        # stream's published "metadata only" guarantee was false. The column is
        # written in the same INSERT as `output_hash`, so hash and hashed value
        # are one row and one write and can never be separately durable.
        row = self.conn.execute(
            """
            SELECT step_name, attempt, status, input_hash, output_hash,
                   provider_response_id, input_tokens, output_tokens, cost_usd, error,
                   output
              FROM extraction_run_steps
             WHERE run_id = %s AND org_id = %s AND step_name = %s AND input_hash = %s
               AND workflow_version = %s AND status = 'succeeded'
             LIMIT 1
            """,
            (run_id, org_id, step_name, input_hash, workflow_version),
        ).fetchone()
        if row is None:
            return None
        output = row[10]
        if isinstance(output, str):
            # psycopg returns jsonb already decoded; a str means a text-typed
            # round trip, so decode it rather than handing back a JSON blob the
            # caller would hash as a string.
            output = json.loads(output)
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
                output, workflow_version, schema_version, prompt_version,
                provider_response_id,
                input_tokens, output_tokens, cost_usd, error, started_at, finished_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s, %s, %s,
                %s,
                %s, %s, %s, %s, now(), now()
            )
            ON CONFLICT DO NOTHING
            """,
            (
                step_id,
                org_id,
                run_id,
                record.step_name,
                record.attempt,
                record.status,
                record.input_hash,
                record.output_hash,
                # One INSERT for the hash and the hashed value: 0006's
                # `CHECK ((output IS NULL) = (output_hash IS NULL))` makes the
                # torn pair unrepresentable rather than merely unlikely.
                json.dumps(record.output) if record.output is not None else None,
                workflow_version,
                "extraction-payload/v1",
                "prompts/v1",
                record.provider_response_id,
                record.input_tokens,
                record.output_tokens,
                record.cost_usd,
                json.dumps(record.error) if record.error is not None else None,
            ),
        )

    def commit_failed(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord:
        """Persist a failed stage attempt and its error.

        0004's replay index is partial (``WHERE status = 'succeeded'``), so a
        failed row cannot collide with it and cannot be mistaken for a resume
        point. Without this, ``extraction_run_steps`` holds no row and no error
        for the step that actually broke, leaving only a run-level message.
        """
        if record.status != "failed":
            raise ValueError("commit_failed requires a failed stage record")
        self._insert_step_row(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
        )
        return self._memory.commit_failed(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
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

        The step row is now self-sufficient: ``output`` and ``output_hash`` are
        written together into ``extraction_run_steps`` (migration 0006 /
        ADR-0011), so a crash between this row and its event costs an audit event,
        not an extraction. Before 0006 it cost the extraction — the event payload
        was the only carrier of a stage's result, and under the worker's
        ``autocommit=True`` connection the two writes were separate transactions,
        so a crash in between left a durably ``succeeded`` step with a non-null
        ``output_hash`` and nothing to hand back. On resume the stage was skipped
        with zero model calls and the run landed ``succeeded`` + ``abstained=True``
        with no proposals: silent data loss reported as a legitimate abstention,
        made permanent by 0004's terminal-run guard.

        The transaction is deliberately KEPT on the narrower rationale. An
        ``extraction_run_steps`` row with no ``step_completed`` event is a hole in
        an append-only audit trail that 0004 makes unrepairable (UPDATE on a
        terminal run and DELETE are both refused), and the cost of keeping the
        pair atomic is one explicit block. ``conn.transaction()`` opens one even
        in autocommit mode, so either both rows land or neither does and the stage
        simply re-runs. The in-process cache is only populated after the block
        commits, so a rollback cannot leave ``load_succeeded`` answering from
        memory for a step whose row no longer exists.

        ``event_payload`` is metadata only. The resume-critical value travels in
        the ``record``, never here — see ``workflow._run_stage``.
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
            (
                org_id,
                run_id,
                event_type,
                json.dumps(redact_event_payload(payload, event_type=event_type)),
            ),
        )
        return event
