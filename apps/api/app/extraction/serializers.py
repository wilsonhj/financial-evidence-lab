"""Deterministic, closed public projections and representation ETags."""

import json
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.extraction.models import PAYLOAD_ADAPTER, ExtractionRun
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.validate.schema import WORKER_EXTENSION_KEYS, allowed_payload_keys

PUBLIC_FIELDS = sorted(
    set().union(
        *(
            allowed_payload_keys(kind, shape=shape)
            for kind, shape in [
                ("kpi", None),
                ("revenue_driver", None),
                *(
                    ("guidance", shape)
                    for shape in ("point", "range", "floor", "ceiling", "qualitative")
                ),
            ]
        )
    )
    - WORKER_EXTENSION_KEYS
)

# Only these deterministic machine codes are public. Free-text worker diagnostics
# can contain source values or unknown field names and are deliberately not echoed.
SAFE_BLOCKERS = frozenset(
    {
        "duplicate_candidate",
        "range_bounds_not_decimal",
        "range_low_gt_high",
        "margin_percent_out_of_range",
        "svc_gm_blended_forbidden",
        "billings_derivation_inputs_missing",
        "crpo_timing_unverified",
        "metric_id_missing",
        "metric_unknown_to_ontology",
    }
)


def display_safe(value: Any) -> bool:
    if type(value) is bool or value is None or isinstance(value, str):
        return True
    if isinstance(value, Decimal):
        return abs(value) <= 9007199254740991 and value == int(value)
    if isinstance(value, int):
        return abs(value) <= 9007199254740991
    if isinstance(value, list):
        return all(display_safe(item) for item in value)
    if isinstance(value, dict):
        return all(display_safe(item) for item in value.values())
    return False


def _safe_integers(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, list):
        return [_safe_integers(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe_integers(item) for key, item in value.items()}
    return value


def candidate_payload(raw: str, field_text: dict[str, str]) -> dict[str, Any]:
    payload = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
    if isinstance(payload, dict):
        clean = {key: value for key, value in payload.items() if key not in WORKER_EXTENSION_KEYS}
        if display_safe(clean):
            clean = {key: _safe_integers(value) for key, value in clean.items()}
            try:
                PAYLOAD_ADAPTER.validate_python(clean)
            except ValidationError:
                pass
            else:
                return clean
    return {"schema_version": "extraction-candidate-fields/v1", "fields": field_text}


def validations(summary: dict[str, Any]) -> list[dict[str, str]]:
    blockers = summary.get("blockers")
    if blockers:
        values = blockers if isinstance(blockers, list) else [blockers]
        codes = {
            item if isinstance(item, str) and item in SAFE_BLOCKERS else "VALIDATION_BLOCKED"
            for item in values
        }
        return [{"code": code, "status": "fail"} for code in sorted(codes)]
    if summary.get("ok") is True:
        return [{"code": "VALIDATION_OK", "status": "pass"}]
    return []


def proposal(
    row: dict[str, Any], evidence: list[dict[str, Any]], conflict_ids: list[str]
) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "kind": row["kind"],
        "metric_id": row["metric_id"],
        "payload": candidate_payload(row["payload_text"], row["field_text"]),
        "evidence": evidence,
        "record_confidence": (
            str(row["record_confidence"]) if row["record_confidence"] is not None else None
        ),
        "field_confidences": row["field_confidences"],
        "validations": validations(row["validation_summary"]),
        "state": row["state"],
        "review_priority": row["review_priority"],
        "version": row["version"],
        "conflict_ids": conflict_ids,
    }


def etag(body: dict[str, Any]) -> str:
    return f'"{hash_json(body)}"'


def safe_error(error: Any) -> dict[str, Any] | None:
    if error is None:
        return None
    return {
        "error": {
            "code": "EXTRACTION_FAILED",
            "message": "Extraction failed.",
            "request_id": "unknown",
            "details": {},
        }
    }


def run(row: dict[str, Any]) -> dict[str, Any]:
    body = {
        key: row[key]
        for key in (
            "id",
            "workspace_id",
            "entity_id",
            "parent_run_id",
            "status",
            "modes",
            "as_of",
            "corpus_version_id",
            "ontology_version",
            "workflow_version",
            "provider",
            "model",
            "version",
            "created_at",
            "cancel_requested_at",
        )
    }
    body["limits"] = {
        key: row[key]
        for key in (
            "max_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_wall_seconds",
        )
    }
    body["limits"]["max_cost_usd"] = str(row["max_cost_usd"])
    body["usage"] = {
        "calls": row["calls_used"],
        "input_tokens": row["input_tokens_used"],
        "output_tokens": row["output_tokens_used"],
        "cost_usd": str(row["cost_usd"]),
    }
    body["error"] = safe_error(row["error"])
    return ExtractionRun.model_validate(body).model_dump(mode="json")


def page(items: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": items,
        **{key: metadata[key] for key in ("limit", "next_cursor", "previous_cursor")},
    }
