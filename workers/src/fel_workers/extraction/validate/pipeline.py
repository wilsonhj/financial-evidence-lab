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
    default_ontology,
    definition_errors,
    duplicate_groups,
    range_errors,
)
from fel_workers.extraction.validate.conflicts import detect_conflicts
from fel_workers.extraction.validate.schema import validate_payload_item

_VALID_KINDS = frozenset({"kpi", "guidance", "revenue_driver"})


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
        kind_raw = clean.get("kind")
        if kind_raw not in _VALID_KINDS:
            continue
        kind = cast(ExtractionMode, kind_raw)

        blockers = _collect_blockers(clean, ontology, evidence_by_span)
        draft = _build_draft(
            run_id=run_id,
            kind=kind,
            clean=clean,
            blockers=blockers,
            ontology=ontology,
            evidence_by_span=evidence_by_span,
        )
        assert draft.state == "needs_review"
        drafts.append(draft)
        cleaned_payloads.append(clean)

    _mark_duplicates(drafts, cleaned_payloads)
    return ValidationResult(proposals=drafts, conflicts=detect_conflicts(drafts))


def _collect_blockers(
    clean: dict[str, Any],
    ontology: OntologyDocument,
    evidence_by_span: dict[str, dict[str, Any]],
) -> list[str]:
    blockers = validate_payload_item(clean)
    blockers.extend(accounting_errors(clean, ontology))
    blockers.extend(range_errors(clean))
    blockers.extend(definition_errors(clean, ontology))
    blockers.extend(citation_errors(clean, evidence_by_span=evidence_by_span))
    return blockers


def _build_draft(
    *,
    run_id: str,
    kind: ExtractionMode,
    clean: dict[str, Any],
    blockers: list[str],
    ontology: OntologyDocument,
    evidence_by_span: dict[str, dict[str, Any]],
) -> ProposalDraft:
    metric_id = str(clean.get("metric_id") or "unknown")
    raw_hash = hash_json(clean)
    definition = clean.get("definition")
    definition_hash = sha256_hex(str(definition)) if definition is not None else sha256_hex("")
    comparability = _comparability(clean, metric_id, ontology, blockers)

    return ProposalDraft(
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
        evidence=_evidence_rows(clean, evidence_by_span=evidence_by_span),
        id=proposal_id_for(
            run_id=run_id, kind=str(kind), metric_id=metric_id, raw_payload_hash=raw_hash
        ),
    )


def _comparability(
    clean: dict[str, Any],
    metric_id: str,
    ontology: OntologyDocument,
    blockers: list[str],
) -> dict[str, Any]:
    try:
        metric = ontology.metric(metric_id)
        quals = {
            str(k): str(v)
            for k, v in (clean.get("qualifiers") or {}).items()
            if v is not None and str(v).strip()
        }
        return {
            "key": build_comparability_key(metric, quals),
            "fields": list(metric.comparability_key_fields),
        }
    except (KeyError, TypeError, ValueError) as exc:
        blockers.append(f"comparability_key unavailable: {exc}")
        return {"key": None, "fields": []}


def _evidence_rows(
    clean: dict[str, Any],
    *,
    evidence_by_span: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build citation rows; pin document_version_id from assembled evidence when omitted."""
    pinned = evidence_by_span or {}
    rows: list[dict[str, Any]] = []
    for item in clean.get("evidence") or []:
        if isinstance(item, dict) and item.get("source_span_id"):
            row = dict(item)
        elif isinstance(item, str):
            row = {"source_span_id": item, "role": "supports", "citation_status": "partial"}
        else:
            continue
        span_id = str(row["source_span_id"])
        if not row.get("document_version_id"):
            pinned_doc = (pinned.get(span_id) or {}).get("document_version_id")
            if pinned_doc:
                row["document_version_id"] = pinned_doc
        rows.append(row)
    return rows


def _mark_duplicates(drafts: list[ProposalDraft], cleaned_payloads: list[dict[str, Any]]) -> None:
    for group in duplicate_groups(cleaned_payloads):
        for idx in group:
            summary = drafts[idx].validation_summary
            summary["duplicate"] = True
            blockers = list(summary.get("blockers") or [])
            blockers.append("duplicate_candidate")
            summary["blockers"] = blockers


__all__ = ["ValidationResult", "detect_conflicts", "validate_proposals"]
