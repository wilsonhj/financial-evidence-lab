"""Compose validators into proposal drafts + deterministic conflict groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from fel_ontology import build_comparability_key
from fel_ontology.models import OntologyDocument
from fel_workers.extraction.errors import IntegrityError
from fel_workers.extraction.hashing import hash_json, proposal_id_for, sha256_hex
from fel_workers.extraction.types import (
    NON_MAGNITUDE_NORMALIZER_BLOCKERS,
    NORMALIZER_BLOCKERS_KEY,
    ConflictDraft,
    ExtractionMode,
    ProposalDraft,
)
from fel_workers.extraction.validate.accounting import identity_errors
from fel_workers.extraction.validate.checks import (
    accounting_errors,
    check_definitions,
    citation_errors,
    default_ontology,
    definition_errors,
    duplicate_groups,
    range_errors,
)
from fel_workers.extraction.validate.conflicts import detect_conflicts
from fel_workers.extraction.validate.schema import (
    PIPELINE_CONTROL_EVIDENCE_KEYS,
    validate_payload_item,
)

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
    # Positions in `cleaned_payloads` (== positions in `drafts`) whose *raw*
    # payload carried a NORMALIZER_BLOCKERS_KEY entry that impugns the row's
    # MAGNITUDE. Collected so `_mark_identity_violations` can exclude these rows
    # from identity consideration (PR #145 review M1) even though the key that
    # identifies them is stripped out of `clean` below and never reaches
    # `cleaned_payloads`.
    #
    # Membership is decided by kind, not by mere presence. This key was built
    # when it carried only scale/sign contradictions — findings that say the
    # row's number cannot be trusted, so arithmetic over it is meaningless.
    # It now also carries advisories that say nothing about the number at all,
    # and excluding a row for one of those silently WITHDRAWS a deterministic
    # accounting check that would otherwise fire: an issuer reporting cRPO
    # $900m against RPO $500m — arithmetically impossible — went entirely
    # unreported because one dimension value arrived as `12` rather than
    # `"12"`. A cosmetic typing note must not disarm the arithmetic.
    normalizer_rejected_indices: set[int] = set()

    for payload in payloads:
        # Strip internal normalizer metadata before schema check / persist.
        clean = {k: v for k, v in payload.items() if not str(k).startswith("_")}
        kind_raw = clean.get("kind")
        if kind_raw not in _VALID_KINDS:
            continue
        kind = cast(ExtractionMode, kind_raw)

        # Blockers the normalizer detected without aborting (a declared scale or
        # sign that contradicts the value) travel on the stripped `_` metadata
        # key, so they survive a crash-resume with the checkpointed payload.
        carried = payload.get(NORMALIZER_BLOCKERS_KEY)
        normalizer_blockers = [str(b) for b in carried] if isinstance(carried, list) else []
        blockers = [*normalizer_blockers, *_collect_blockers(clean, ontology, evidence_by_span)]
        # The normalizer's scale check and range_errors deliberately overlap
        # (defense in depth on either side of normalization) and word the finding
        # identically, so collapse exact repeats — a reviewer reading the summary
        # should see each distinct problem once.
        blockers = _dedupe(blockers)
        draft = _build_draft(
            run_id=run_id,
            kind=kind,
            clean=clean,
            blockers=blockers,
            ontology=ontology,
            evidence_by_span=evidence_by_span,
        )
        if draft.state != "needs_review":
            # errors.py: never emit a proposal that is not awaiting review.
            raise IntegrityError(f"proposal state must be needs_review, got {draft.state!r}")
        drafts.append(draft)
        cleaned_payloads.append(clean)
        if any(b not in NON_MAGNITUDE_NORMALIZER_BLOCKERS for b in normalizer_blockers):
            normalizer_rejected_indices.add(len(cleaned_payloads) - 1)

    _mark_duplicates(drafts, cleaned_payloads)
    _mark_identity_violations(drafts, cleaned_payloads, normalizer_rejected_indices)
    return ValidationResult(proposals=drafts, conflicts=detect_conflicts(drafts))


def _dedupe(blockers: list[str]) -> list[str]:
    """Order-preserving de-duplication of blocker strings."""
    seen: set[str] = set()
    out: list[str] = []
    for blocker in blockers:
        if blocker not in seen:
            seen.add(blocker)
            out.append(blocker)
    return out


def _collect_blockers(
    clean: dict[str, Any],
    ontology: OntologyDocument,
    evidence_by_span: dict[str, dict[str, Any]],
) -> list[str]:
    # `check_definitions` is called here and nowhere else. It existed with zero
    # call sites, so its unit/period/currency cross-checks against the ontology
    # were never applied to a single proposal. `check_accounting`'s rules —
    # billings lineage, cRPO timing, blended-margin proxying — now live inside
    # `accounting_errors` itself rather than in a second function that has to be
    # remembered separately.
    blockers = validate_payload_item(clean)
    blockers.extend(accounting_errors(clean, ontology))
    blockers.extend(range_errors(clean))
    blockers.extend(definition_errors(clean, ontology))
    blockers.extend(check_definitions(clean, ontology))
    blockers.extend(
        citation_errors(
            clean,
            evidence_by_span=evidence_by_span,
            expected_hashes=_claimed_span_hashes(clean),
        )
    )
    return blockers


def _claimed_span_hashes(clean: dict[str, Any]) -> dict[str, str]:
    """Span hashes the *model* asserted, keyed by span id.

    ``citation_errors`` compares these against the hash of the pinned evidence,
    so a proposal that cites a span while asserting a different digest for it is
    blocked. Without this the hash branch of ``citation_errors`` never executed:
    the only caller passed no ``expected_hashes``.

    The pinned text is verified against its own hash separately and earlier, in
    ``workflow._stage_assemble_evidence`` (and again in ``_restore_output`` on
    resume) — that is where the "evidence text matches its content address"
    guarantee lives. This check is the different one: the *citation* must agree
    with the pinned span it points at.
    """
    claimed: dict[str, str] = {}
    for item in clean.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        span_id = item.get("source_span_id")
        text_hash = item.get("text_hash")
        if span_id and isinstance(text_hash, str) and text_hash:
            claimed[str(span_id)] = text_hash
    return claimed


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


def citation_status_for(
    row: dict[str, Any],
    *,
    evidence_by_span: dict[str, dict[str, Any]],
) -> str:
    """Grade one citation row from the pinned evidence alone.

    The single rule behind every `citation_status` the pipeline writes, so a
    draft rebuilt on crash-resume and one graded by `workflow._stage_verify_citations`
    can never disagree. It reads only the pinned span map — never a value the
    model supplied — because `extraction_proposal_evidence` is append-only
    (`db/migrations/0004_extraction_core.sql`) and a wrong grade is permanent.

    * `invalid` — the row names no span, names one that is not pinned, or asserts
      a `text_hash` that does not describe the span it cites. All three are
      citations that cannot support anything.
    * `verified` — the row asserted the span's content address and it matched.
      This is the only claim code can prove: a role that actually opened the span
      through the `read_span` tool has its `text_hash` (see `extraction/tools.py`).
    * `partial` — the span is pinned but the row asserted nothing further about
      its content. Membership alone is not verification, and it is what a
      string-form citation (`"evidence": ["<span-id>"]`) can express at most, so
      grading it `verified` would let the model upgrade a citation by choosing a
      JSON shape.

    `contradictory` is never returned: nothing in the pipeline evaluates whether
    the cited evidence contradicts the claim, and claiming it would be a guess.
    """
    span_id = row.get("source_span_id")
    if not isinstance(span_id, str) or not span_id.strip():
        return "invalid"
    pinned = evidence_by_span.get(span_id)
    if pinned is None:
        return "invalid"
    asserted = row.get("text_hash")
    if isinstance(asserted, str) and asserted:
        actual = pinned.get("text_hash") or sha256_hex(str(pinned.get("text") or ""))
        return "verified" if asserted == actual else "invalid"
    return "partial"


def _evidence_rows(
    clean: dict[str, Any],
    *,
    evidence_by_span: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build citation rows; pin document_version_id from assembled evidence when omitted.

    Every row is graded here by `citation_status_for`, and any model-supplied
    grade is dropped first. Grading at build time rather than only in
    `workflow._stage_verify_citations` is what keeps a draft rebuilt on
    crash-resume — where that stage is replayed from its checkpoint and never
    re-runs — from reaching persist ungraded.
    """
    pinned = evidence_by_span or {}
    rows: list[dict[str, Any]] = []
    for item in clean.get("evidence") or []:
        if isinstance(item, dict) and item.get("source_span_id"):
            row = {k: v for k, v in item.items() if k not in PIPELINE_CONTROL_EVIDENCE_KEYS}
        elif isinstance(item, str):
            row = {"source_span_id": item, "role": "supports"}
        else:
            continue
        span_id = str(row["source_span_id"])
        if not row.get("document_version_id"):
            pinned_doc = (pinned.get(span_id) or {}).get("document_version_id")
            if pinned_doc:
                row["document_version_id"] = pinned_doc
        row["citation_status"] = citation_status_for(row, evidence_by_span=pinned)
        rows.append(row)
    return rows


def _mark_identity_violations(
    drafts: list[ProposalDraft],
    cleaned_payloads: list[dict[str, Any]],
    normalizer_rejected_indices: set[int],
) -> None:
    """Attach cross-payload accounting identity breaks (M3-VAL-001).

    Runs after the per-payload pass because an identity is a property of a set
    of proposals, not of any one of them: ``accounting_errors`` never sees the
    RPO row while it is validating the cRPO row. Every member of a broken
    identity is blocked, since nothing here can tell which figure is wrong.

    ``normalizer_rejected_indices`` excludes rows the normalizer already
    rejected from identity consideration (PR #145 review M1): such a row is
    not a competing fact and must not read as one to ``identity_errors``' own
    ambiguity handling — see that function's docstring for why leaving it in
    would silently disable the identity for its clean siblings too.
    """
    codes_by_index = identity_errors(
        cleaned_payloads, excluded_indices=frozenset(normalizer_rejected_indices)
    )
    for index, codes in codes_by_index.items():
        summary = drafts[index].validation_summary
        blockers = _dedupe([*(summary.get("blockers") or []), *codes])
        summary["blockers"] = blockers
        summary["ok"] = False


def _mark_duplicates(drafts: list[ProposalDraft], cleaned_payloads: list[dict[str, Any]]) -> None:
    for group in duplicate_groups(cleaned_payloads):
        for idx in group:
            summary = drafts[idx].validation_summary
            summary["duplicate"] = True
            blockers = list(summary.get("blockers") or [])
            blockers.append("duplicate_candidate")
            summary["blockers"] = blockers


__all__ = ["ValidationResult", "citation_status_for", "detect_conflicts", "validate_proposals"]
