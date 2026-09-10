"""Extraction checkpoint persistence definitions."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg

from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.errors import LeaseLost
from fel_workers.extraction.types import StageRecord


@dataclass
class PostgresCheckpointStore:
    conn: psycopg.Connection[Any]
    _memory: MemoryCheckpointStore = field(default_factory=MemoryCheckpointStore)

    # Row identity and MVCC version are captured at read time, independently of
    # the mutable StageRecord returned to workflow validation.
    _loaded: dict[tuple[str, ...], tuple[StageRecord, str, str]] = field(default_factory=dict)
    _rejected: dict[tuple[str, ...], tuple[str, str]] = field(default_factory=dict)

    def reject_loaded(
        self, *, run_id: str, org_id: str, workflow_version: str, record: StageRecord
    ) -> None:
        key = (run_id, org_id, record.step_name, record.input_hash, workflow_version)
        loaded = self._loaded.get(key)
        if loaded is not None and loaded[0] is record:
            self._rejected[key] = (loaded[1], loaded[2])

    def load_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        step_name: str,
        input_hash: str,
        workflow_version: str,
    ) -> StageRecord | None:
        key = (run_id, org_id, step_name, input_hash, workflow_version)
        self._loaded.pop(key, None)
        self._rejected.pop(key, None)
        # Always read the current row: a cached value has no current MVCC token
        # and may have been replaced by another worker since our last commit.
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
                   output, id::text, xmin::text
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
        record = StageRecord(
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
        self._loaded[key] = (record, row[11], row[12])
        return record

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
        # A repair replaces a cached success too, but only after the DB write
        # (and, on the atomic path, its event) has committed.
        self._memory = MemoryCheckpointStore()
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
        if record.status == "succeeded":
            # Failed attempts are immutable audit rows. A resumed execution
            # needs a free attempt, while the success-key index still arbitrates
            # concurrent successes. A race at either key fails closed below.
            next_attempt = self.conn.execute(
                """
                SELECT max(attempt) + 1 FROM extraction_run_steps
                 WHERE run_id = %s AND org_id = %s AND step_name = %s
                   AND EXISTS (
                       SELECT 1 FROM extraction_run_steps
                        WHERE run_id = %s AND org_id = %s AND step_name = %s
                          AND attempt = %s AND status = 'failed'
                   )
                """,
                (
                    run_id,
                    org_id,
                    record.step_name,
                    run_id,
                    org_id,
                    record.step_name,
                    record.attempt,
                ),
            ).fetchone()
            if next_attempt is not None and next_attempt[0] is not None:
                record.attempt = next_attempt[0]
        step_id = str(uuid.uuid4())
        inserted = self.conn.execute(
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
            RETURNING id
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
        ).fetchone()
        if inserted is None and record.status == "succeeded":
            key = (run_id, org_id, record.step_name, record.input_hash, workflow_version)
            version = self._rejected.get(key)
            if version is None:
                self._memory = MemoryCheckpointStore()
                raise LeaseLost(
                    "checkpoint conflict without rejected row", code="checkpoint_superseded"
                )
            # Only the exact row rejected by this worker can be repaired. A
            # concurrent insert/repair must not lose its output or gain a stale
            # completion event/cache entry when this compare-and-swap misses.
            repaired = self.conn.execute(
                """
                UPDATE extraction_run_steps
                   SET output = %s::jsonb, output_hash = %s,
                       provider_response_id = %s, input_tokens = %s,
                       output_tokens = %s, cost_usd = %s, error = %s::jsonb,
                       finished_at = now()
                 WHERE run_id = %s AND org_id = %s AND step_name = %s
                   AND input_hash = %s AND workflow_version = %s
                   AND status = 'succeeded' AND id = %s AND xmin::text = %s
                RETURNING attempt
                """,
                (
                    json.dumps(record.output) if record.output is not None else None,
                    record.output_hash,
                    record.provider_response_id,
                    record.input_tokens,
                    record.output_tokens,
                    record.cost_usd,
                    json.dumps(record.error) if record.error is not None else None,
                    run_id,
                    org_id,
                    record.step_name,
                    record.input_hash,
                    workflow_version,
                    *version,
                ),
            ).fetchone()
            if repaired is None:
                self._memory = MemoryCheckpointStore()
                raise LeaseLost("checkpoint changed since rejection", code="checkpoint_superseded")
            record.attempt = repaired[0]

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
                payload={**event_payload, "attempt": record.attempt},
            )
        # A repair replaces a cached success too, but only after the DB write
        # (and, on the atomic path, its event) has committed.
        self._memory = MemoryCheckpointStore()
        return self._memory.commit_succeeded(
            run_id=run_id, org_id=org_id, workflow_version=workflow_version, record=record
        )
