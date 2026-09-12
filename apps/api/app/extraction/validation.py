"""Compose existing deterministic rules with freshly verified, immutable source pins."""

from dataclasses import dataclass
from typing import Any

import psycopg
from pydantic import ValidationError

from app.errors import api_error
from app.extraction import evidence, reads
from app.extraction.models import PAYLOAD_ADAPTER
from fel_ontology import load_saas_metrics
from fel_ontology.units import UNIT_POLICY_VERSION
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.normalize.pipeline import normalize_payload
from fel_workers.extraction.types import (
    NORMALIZER_BLOCKERS_KEY,
    NORMALIZER_VERSION,
    RANGE_POLICY_VERSION,
    VALIDATOR_VERSION,
    WORKFLOW_VERSION,
    ConflictDraft,
    ProposalDraft,
)
from fel_workers.extraction.validate.pipeline import detect_conflicts, validate_proposals
from fel_workers.extraction.validate.schema import WORKER_EXTENSION_KEYS


@dataclass
class Evaluated:
    drafts: dict[str, ProposalDraft]
    conflicts: list[ConflictDraft]
    context: dict[str, Any]


def invalid(resource_id: str) -> None:
    raise api_error(
        422, "VALIDATION_ERROR", "Extraction failed revalidation.", {"resource_id": resource_id}
    )


def source_context(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "extraction-validation-context/v1",
        "workflow_version": WORKFLOW_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "unit_policy_version": UNIT_POLICY_VERSION,
        "range_policy_version": RANGE_POLICY_VERSION,
        "source_runs": [
            {
                "run_id": key,
                "as_of": run["as_of"].isoformat(),
                **{
                    field: str(run[field])
                    for field in (
                        "corpus_version_id",
                        "ontology_version",
                        "workflow_version",
                        "policy_id",
                    )
                },
            }
            for key, run in sorted(runs.items())
        ],
    }


def evaluate(
    conn: psycopg.Connection[dict[str, Any]],
    rows: list[dict[str, Any]],
    runs: dict[str, dict[str, Any]],
) -> Evaluated:
    """Rows are the complete locked comparison set; IDs remain source-row identities."""
    if len(rows) > 200 or len(runs) > 100:
        raise reads.too_large(rows[0]["id"])
    scopes, pinned = _verified_scopes(conn, rows, runs)
    payloads = []
    for row in rows:
        resource = str(row["id"])
        run = runs[str(row["run_id"])]
        run_ids = row.get("source_run_ids") or [str(row["run_id"])]
        local = {span: block for rid in run_ids for span, block in scopes[rid].items()}
        verified = []
        for edge in row["evidence"]:
            block = local.get(str(edge["source_span_id"]))
            if block is None or str(edge["document_version_id"]) != block["document_version_id"]:
                invalid(resource)
            assert block is not None
            verified.append(
                {
                    "source_span_id": block["source_span_id"],
                    "document_version_id": block["document_version_id"],
                    "text_hash": block["text_hash"],
                    "role": edge["role"],
                }
            )
        for assertion in row["payload"].get("evidence") or []:
            if isinstance(assertion, dict) and assertion.get("text_hash"):
                asserted_block = local.get(str(assertion.get("source_span_id")))
                if asserted_block is None or assertion["text_hash"] != asserted_block["text_hash"]:
                    invalid(resource)
        public = {k: v for k, v in row["payload"].items() if k not in WORKER_EXTENSION_KEYS}
        try:
            PAYLOAD_ADAPTER.validate_python(public)
        except ValidationError:
            invalid(resource)
        if public.get("entity_id") != str(run["entity_id"]):
            invalid(resource)
        normalized, blockers = normalize_payload({**public, "evidence": verified})
        if blockers:
            normalized[NORMALIZER_BLOCKERS_KEY] = [
                *(normalized.get(NORMALIZER_BLOCKERS_KEY) or []),
                *blockers,
            ]
        payloads.append(normalized)
    result = validate_proposals(run_id="review", payloads=payloads, evidence_by_span=pinned)
    if len(result.proposals) != len(rows):
        invalid(str(rows[0]["id"]))
    drafts = {}
    for row, draft in zip(rows, result.proposals, strict=True):
        carried = (row.get("validation_summary") or {}).get("blockers") or []
        # The persisted normalizer may already have changed a rejected sign.
        # Unchanged source candidates retain those findings; explicit replacements
        # have no old summary and are independently validated above.
        blockers = list(draft.validation_summary["blockers"])
        for blocker in carried:
            irreversible = isinstance(blocker, str) and (
                blocker == "dimensions_non_string"
                or blocker.startswith("sign contradicts value:")
                or blocker.startswith("sign must be positive/negative/zero:")
            )
            if irreversible and blocker not in blockers:
                blockers.append(blocker)
        draft.validation_summary["blockers"] = blockers
        draft.validation_summary["ok"] = not blockers
        draft.id = str(row["id"])
        drafts[draft.id] = draft
    return Evaluated(drafts, detect_conflicts(list(drafts.values())), source_context(runs))


def _verified_scopes(
    conn: psycopg.Connection[dict[str, Any]],
    rows: list[dict[str, Any]],
    runs: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """One bounded real-byte verification per immutable run scope, shared by its rows."""
    scopes: dict[str, dict[str, Any]] = {}
    pinned: dict[str, Any] = {}
    for rid, run in sorted(runs.items()):
        manifest = run["input_manifest"]
        if (
            run["workflow_version"] != WORKFLOW_VERSION
            or run["ontology_version"] != load_saas_metrics().schema_version
            or not isinstance(manifest, dict)
            or hash_json(manifest) != run["input_hash"]
            or (
                "conflict_occurrence_policy" in manifest
                and manifest["conflict_occurrence_policy"] != "run/v1"
            )
        ):
            invalid(rid)
        pins = manifest.get("evidence")
        if not isinstance(pins, list) or not all(isinstance(pin, dict) for pin in pins):
            invalid(rid)
        pin_map = {str(pin.get("source_span_id")): pin for pin in pins}
        if len(pin_map) != len(pins) or len(pins) > 200:
            invalid(rid)
        requested: set[str] = set()
        for row in rows:
            source_ids = row.get("source_run_ids") or [str(row["run_id"])]
            if rid not in source_ids:
                continue
            if not row["evidence"] or len(row["evidence"]) > 200:
                invalid(str(row["id"]))
            requested.update(
                str(edge["source_span_id"])
                for edge in row["evidence"]
                if str(edge["source_span_id"]) in pin_map
            )
        blocks = (
            evidence.verify_spans(
                conn,
                sorted(requested),
                str(run["entity_id"]),
                str(run["corpus_version_id"]),
                run["as_of"],
            )
            if requested
            else []
        )
        for block in blocks:
            pin = pin_map[block["source_span_id"]]
            if any(
                pin.get(field) != block[field] for field in ("document_version_id", "text_hash")
            ):
                invalid(rid)
        scopes[rid] = {block["source_span_id"]: block for block in blocks}
        pinned.update(scopes[rid])
    if sum(len(block["text"].encode()) for block in pinned.values()) > 8 * 1024 * 1024:
        raise reads.too_large(str(rows[0]["id"]))
    return scopes, pinned
