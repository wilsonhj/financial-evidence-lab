"""Checkpoint/resume store for content-addressed stage successes (M3-101)."""

from __future__ import annotations

from dataclasses import dataclass, field

from fel_workers.extraction.types import StageRecord


@dataclass
class MemoryCheckpointStore:
    """In-memory success-keyed checkpoint used by unit tests and mock E2E.

    Success identity matches migration 0004:
    ``(run_id, step_name, input_hash, workflow_version) WHERE status='succeeded'``.
    """

    _succeeded: dict[tuple[str, str, str, str], StageRecord] = field(default_factory=dict)
    _by_run: dict[str, list[StageRecord]] = field(default_factory=dict)

    def load_succeeded(
        self, *, run_id: str, step_name: str, input_hash: str, workflow_version: str
    ) -> StageRecord | None:
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

    def list_succeeded(self, *, run_id: str) -> list[StageRecord]:
        return [r for r in self._by_run.get(run_id, []) if r.status == "succeeded"]


__all__ = ["MemoryCheckpointStore"]
