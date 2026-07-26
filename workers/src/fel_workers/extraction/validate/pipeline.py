"""Compose validators into proposal drafts + deterministic conflict groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from fel_ontology import build_comparability_key
from fel_ontology.models import OntologyDocument
from fel_workers.extraction.hashing import hash_json, proposal_id_for, sha256_hex
from fel_workers.extraction.types import ConflictDraft, ExtractionMode, ProposalDraft
from fel_workers.extraction.validate.checks import (
    accounting_errors,
    citation_errors,
    conflict_key_for,
    default_ontology,
    definition_errors,
    duplicate_groups,
    range_errors,
    value_fingerprint,
)
from fel_workers.extraction.validate.schema import validate_payload_item


@dataclass
class ValidationResult:
    proposals: list[ProposalDraft] = field(default_factory=list)
    conflicts: list[ConflictDraft] = field(default_factory=list)


def validate_proposals(
    *,
    run_id: str,
    payloads: list[dict[str, Any]],
    evidence_by_span: dict[str, dict[str, Any]] | None = None,
    ontology: OntologyDocument | None = None,
) -> ValidationResult:
    """Validate normalized payloads; every draft state is needs_review."""
    ontology = ontology or default_ontology()
    evidence_by_span = evidence_by_span or {}
    drafts: list[ProposalDraft] = []
    cleaned_payloads: list[dict[str, Any]] = []

    for payload in payloads:
        # Strip internal normalizer metadata before schema check / persist.
        clean = {k: v for k, v in payload.items() if not str(k).startswith("_")}
        blockers = validate_payload_item(clean)
        blockers.extend(accounting_errors(clean, ontology))
        blockers.extend(range_errors(clean))
        blockers.extend(definition_errors(clean, ontology))
        blockers.extend(citation_errors(clean, evidence_by_span=evidence_by_span))

        kind_raw = clean.get("kind")
        if kind_raw not in {"kpi", "guidance", "revenue_driver"}:
            continue
        kind = cast(ExtractionMode, kind_raw)
        metric_id = str(clean.get("metric_id") or "unknown")
        raw_hash = hash_json(clean)
        definition = clean.get("definition")
        definition_hash = sha256_hex(str(definition)) if definition is not None else sha256_hex("")

        comparability: dict[str, Any] = {}
        try:
            metric = ontology.metric(metric_id)
            quals = {
                str(k): str(v)
                for k, v in (clean.get("qualifiers") or {}).items()
                if v is not None and str(v).strip()
            }
            comparability = {
                "key": build_comparability_key(metric, quals),
                "fields": list(metric.comparability_key_fields),
            }
        except (KeyError, TypeError, ValueError) as exc:
            blockers.append(f"comparability_key unavailable: {exc}")
            comparability = {"key": None, "fields": []}

        evidence_rows: list[dict[str, Any]] = []
        for item in clean.get("evidence") or []:
            if isinstance(item, dict) and item.get("source_span_id"):
                evidence_rows.append(dict(item))
            elif isinstance(item, str):
                evidence_rows.append(
                    {"source_span_id": item, "role": "supports", "citation_status": "partial"}
                )

        draft = ProposalDraft(
            kind=kind,
            metric_id=metric_id,
            payload=clean,
            raw_payload_hash=raw_hash,
            definition_hash=definition_hash,
            comparability_key=comparability,
            record_confidence=Decimal("0"),
            field_confidences={},
            validation_summary={
                "ok": not blockers,
                "blockers": blockers,
                "duplicate": False,
            },
            review_priority="high",
            evidence=evidence_rows,
            id=proposal_id_for(
                run_id=run_id, kind=str(kind), metric_id=metric_id, raw_payload_hash=raw_hash
            ),
        )
        assert draft.state == "needs_review"
        drafts.append(draft)
        cleaned_payloads.append(clean)

    for group in duplicate_groups(cleaned_payloads):
        for idx in group:
            drafts[idx].validation_summary["duplicate"] = True
            blockers = list(drafts[idx].validation_summary.get("blockers") or [])
            blockers.append("duplicate_candidate")
            drafts[idx].validation_summary["blockers"] = blockers

    conflicts = detect_conflicts(drafts)
    return ValidationResult(proposals=drafts, conflicts=conflicts)


def detect_conflicts(drafts: list[ProposalDraft]) -> list[ConflictDraft]:
    """Group proposals that share conflict_key and disagree or duplicate."""
    by_key: dict[str, list[ProposalDraft]] = {}
    for draft in drafts:
        key = conflict_key_for(draft.payload)
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


__all__ = ["ValidationResult", "detect_conflicts", "validate_proposals"]
