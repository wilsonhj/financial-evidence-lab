"""Deterministic extraction-level conflict groups (live path)."""

from __future__ import annotations

from fel_workers.extraction.types import ConflictDraft, ProposalDraft
from fel_workers.extraction.validate.duplicates import conflict_key_for, value_fingerprint


def _ontology_key(draft: ProposalDraft) -> str | None:
    key = draft.comparability_key.get("key") if draft.comparability_key else None
    return key if isinstance(key, str) and key else None


def detect_conflicts(drafts: list[ProposalDraft]) -> list[ConflictDraft]:
    """Group proposals that share conflict_key and disagree or duplicate.

    Grouping is primarily by ontology comparability key
    (``draft.comparability_key["key"]``) so non-comparable definitions
    (e.g. NRR with different ``base_quantity``) never share a conflict.
    """
    by_key: dict[str, list[ProposalDraft]] = {}
    for draft in drafts:
        key = conflict_key_for(
            draft.payload,
            ontology_comparability_key=_ontology_key(draft),
        )
        by_key.setdefault(key, []).append(draft)

    conflicts: list[ConflictDraft] = []
    for key, members in sorted(by_key.items(), key=lambda kv: kv[0]):
        if len(members) < 2:
            continue
        fingerprints = {value_fingerprint(m.payload) for m in members}
        member_ids = sorted(m.id for m in members if m.id)
        if len(member_ids) < 2:
            continue
        reasons: list[str] = []
        if len(fingerprints) >= 2:
            reasons.append("value_disagreement")
        if len(fingerprints) == 1 or any(m.validation_summary.get("duplicate") for m in members):
            reasons.append("duplicate_candidate")
        if not reasons:
            continue
        conflicts.append(
            ConflictDraft(
                conflict_key=key,
                reason_codes=sorted(set(reasons)),
                member_proposal_ids=member_ids,
            )
        )
    return conflicts


__all__ = ["detect_conflicts"]
