"""Checkpoint/resume store for content-addressed stage successes (M3-101)."""

from __future__ import annotations

from dataclasses import dataclass, field

from fel_workers.extraction.types import StageRecord


@dataclass
class MemoryCheckpointStore:
    """In-memory success-keyed checkpoint used by unit tests and mock E2E.

    Success identity matches migration 0004:
    ``(run_id, step_name, input_hash, workflow_version) WHERE status='succeeded'``.

    The stored ``StageRecord`` mirrors the durable row's shape exactly, which is
    the point of the double: ``record.output`` holds the SERIALIZED stage output
    (what ``extraction_run_steps.output`` receives) and ``record.output_hash``
    holds ``hash_json`` over that same value, so ``workflow._is_recoverable``'s
    hash verification exercises the identical code path here and against
    Postgres. A double that kept the pre-serialization object would make the
    memory suite unable to see a hash mismatch at all.

    There is no ``commit_succeeded_atomic`` here on purpose: a dict has no
    durability boundary for the step row and its event to straddle, so
    ``workflow._commit_stage`` falls back to the two-call form.
    """

    _succeeded: dict[tuple[str, str, str, str], StageRecord] = field(default_factory=dict)
    _by_run: dict[str, list[StageRecord]] = field(default_factory=dict)

    def load_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        step_name: str,
        input_hash: str,
        workflow_version: str,
    ) -> StageRecord | None:
        del org_id  # ownership validated by caller; success key is content-addressed
        return self._succeeded.get((run_id, step_name, input_hash, workflow_version))

    def commit_succeeded(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord:
        del org_id  # ownership validated by caller
        if record.status != "succeeded":
            raise ValueError("only succeeded stages may be checkpointed")
        key = (run_id, record.step_name, record.input_hash, workflow_version)
        existing = self._succeeded.get(key)
        if existing is not None:
            return existing
        self._succeeded[key] = record
        self._by_run.setdefault(run_id, []).append(record)
        return record

    def commit_failed(
        self,
        *,
        run_id: str,
        org_id: str,
        workflow_version: str,
        record: StageRecord,
    ) -> StageRecord:
        """Record a failed stage attempt.

        Deliberately NOT keyed into ``_succeeded``: the resume key is
        success-only (0004's partial unique index is ``WHERE status =
        'succeeded'``), so a failed attempt must never satisfy a later
        ``load_succeeded``. It exists so a failing step leaves a diagnosable
        row and its error behind instead of only a run-level message.
        """
        del org_id, workflow_version  # ownership validated by caller; not part of the failure key
        if record.status != "failed":
            raise ValueError("commit_failed requires a failed stage record")
        self._by_run.setdefault(run_id, []).append(record)
        return record

    def list_succeeded(self, *, run_id: str) -> list[StageRecord]:
        return [r for r in self._by_run.get(run_id, []) if r.status == "succeeded"]

    def list_failed(self, *, run_id: str) -> list[StageRecord]:
        return [r for r in self._by_run.get(run_id, []) if r.status == "failed"]


__all__ = ["MemoryCheckpointStore"]
