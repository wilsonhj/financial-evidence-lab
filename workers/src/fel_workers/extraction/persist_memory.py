"""Extraction memory persistence definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.hashing import proposal_id_for
from fel_workers.extraction.persist_types import (
    TERMINAL_RUN_STATUSES,
    RunAlreadyTerminal,
    UsageSnapshot,
    _ensure_needs_review,
)
from fel_workers.extraction.types import ConflictDraft, ProposalDraft


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

    def _assert_run_open(self, run_id: str) -> None:
        """The 0004 terminal guard, so unit tests reject what Postgres rejects."""
        status = self.run_status.get(run_id)
        if status is not None and status in TERMINAL_RUN_STATUSES:
            raise RunAlreadyTerminal(run_id=run_id, status=status)

    def load_run_status(self, *, run_id: str, org_id: str) -> str | None:
        del org_id
        return self.run_status.get(run_id)

    def set_run_status(
        self,
        *,
        run_id: str,
        org_id: str,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        del org_id, error
        self._assert_run_open(run_id)
        self.run_status[run_id] = status

    def record_usage(self, *, run_id: str, org_id: str, usage: UsageSnapshot) -> None:
        del org_id
        self.usage[run_id] = usage

    def load_usage(self, *, run_id: str, org_id: str) -> UsageSnapshot:
        del org_id
        return self.usage.get(run_id, UsageSnapshot())

    def mark_running(self, *, run_id: str, org_id: str) -> None:
        del org_id
        self._assert_run_open(run_id)
        self.run_status[run_id] = "running"
