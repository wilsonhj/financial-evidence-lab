"""Frozen extraction-payload schema validation (stdlib; no network)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any
from uuid import UUID

from fel_workers.extraction.contracts import EXTRACTION_PAYLOAD_SCHEMA_FILENAME

_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PERIOD_TYPES = frozenset({"instant", "duration", "trailing_window", "forecast"})
_DRIVER_CATEGORIES = frozenset(
    {
        "price",
        "volume",
        "mix",
        "acquisition",
        "retention",
        "usage",
        "seats",
        "fx",
        "services",
        "cost",
        "other",
    }
)
_SCHEMA_VERSION = "extraction-payload/v1"

# Keys the worker pipeline genuinely reads that the frozen contract does not
# define. `evidence` carries citation rows (`validate/pipeline.py::_evidence_rows`,
# `validate/citations.py::citation_errors`); `source_span_ids` is the flat
# alternative `citation_errors` accepts. Nothing else may ride along: the
# contract sets `additionalProperties: false` on every variant, and an unknown
# key is how model-supplied control fields reached persistence.
WORKER_EXTENSION_KEYS = frozenset({"evidence", "source_span_ids"})

# Fields on a citation row that the pipeline computes for itself. A
# model-supplied value is a self-grade, so it is reported here and dropped in
# `validate/pipeline.py::_evidence_rows`.
PIPELINE_CONTROL_EVIDENCE_KEYS = frozenset({"citation_status"})

# `$defs` names of the closed variants, keyed by the payload's own discriminator.
_GUIDANCE_SHAPE_DEFS = {
    "point": "guidancePoint",
    "range": "guidanceRange",
    "floor": "guidanceFloor",
    "ceiling": "guidanceCeiling",
    "qualitative": "guidanceQualitative",
}
_COMMON_REQUIRED = (
    "schema_version",
    "kind",
    "entity_id",
    "issuer_label",
    "metric_id",
    "raw_value",
    "period",
    "dimensions",
    "qualifiers",
    "reported_or_derived",
)
_KPI_REQUIRED = _COMMON_REQUIRED + ("value", "unit", "scale", "sign")
_GUIDANCE_REQUIRED = _COMMON_REQUIRED + ("shape",)
_DRIVER_REQUIRED = _COMMON_REQUIRED + (
    "category",
    "description",
    "direction",
    "target_metric_ids",
)


@lru_cache(maxsize=1)
def load_extraction_payload_schema() -> dict[str, Any]:
    """Load the frozen contract schema from package data (read-only reference).

    Read out of ``fel_workers.extraction.contracts`` rather than off the
    repository tree. The previous loader walked parent directories looking for
    ``packages/contracts/schemas/…``, which resolves in a git checkout and in no
    other deployment: installed as a wheel, ``fel_workers`` sits in
    ``site-packages`` with no repository above it, the walk runs to the
    filesystem root, and the worker raises ``FileNotFoundError`` on the first
    payload it validates — at runtime, on a real job, not at build time
    (issue #192).

    ``packages/contracts/schemas/extraction-payload.schema.json`` remains
    AUTHORITATIVE; the packaged copy is a byte-for-byte mirror of it and
    ``test_vendored_contract_schema.py`` fails CI on any drift, so this cannot
    become a second source of truth by accident.
    """
    raw = (
        resources.files("fel_workers.extraction.contracts")
        .joinpath(EXTRACTION_PAYLOAD_SCHEMA_FILENAME)
        .read_text(encoding="utf-8")
    )
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise TypeError("extraction payload schema root must be an object")
    return loaded


def _closed_branch_properties(node: dict[str, Any]) -> set[str]:
    """Property names of the `allOf` member that closes the object.

    The guidance variants are `allOf: [guidanceBase, <closed branch>]`, and only
    the closed branch carries `additionalProperties: false`, so it alone decides
    which keys that shape may carry.
    """
    for member in node.get("allOf") or []:
        if isinstance(member, dict) and member.get("additionalProperties") is False:
            return set(member.get("properties") or {})
    return set()


def allowed_payload_keys(kind: Any, *, shape: Any) -> set[str]:
    """Keys this payload variant may carry, read off the frozen contract schema.

    Derived at call time from the frozen contract schema
    (`packages/contracts/schemas/extraction-payload.schema.json`, read from the
    packaged mirror)
    (consumed, never modified) so the allowed set cannot drift from the contract.
    An empty set means the variant is unrecognisable — `kind`/`shape` is already
    reported as an error, and no unknown-key noise is added on top of it.
    """
    defs = load_extraction_payload_schema().get("$defs") or {}
    if kind == "kpi":
        properties = set((defs.get("kpi") or {}).get("properties") or {})
    elif kind == "revenue_driver":
        properties = set((defs.get("revenueDriver") or {}).get("properties") or {})
    elif kind == "guidance":
        name = _GUIDANCE_SHAPE_DEFS.get(str(shape))
        properties = _closed_branch_properties(defs.get(name) or {}) if name else set()
    else:
        properties = set()
    if not properties:
        return set()
    return properties | set(WORKER_EXTENSION_KEYS)


def _unknown_key_errors(payload: dict[str, Any]) -> list[str]:
    allowed = allowed_payload_keys(payload.get("kind"), shape=payload.get("shape"))
    if not allowed:
        return []
    return [
        f"unknown field not permitted by {_SCHEMA_VERSION}: {key}"
        for key in sorted(payload)
        if key not in allowed
    ]


def _evidence_control_field_errors(payload: dict[str, Any]) -> list[str]:
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        return []
    errors: list[str] = []
    for idx, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        for key in sorted(PIPELINE_CONTROL_EVIDENCE_KEYS.intersection(item)):
            errors.append(f"evidence[{idx}]: {key} is set by the pipeline, not the model")
    return errors


def validate_payload_item(payload: dict[str, Any]) -> list[str]:
    """Return human-readable errors; empty list means schema-valid."""
    if not isinstance(payload, dict):
        return ["payload must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != _SCHEMA_VERSION:
        errors.append("schema_version must be extraction-payload/v1")
    kind = payload.get("kind")
    if kind == "kpi":
        errors.extend(_validate_kpi(payload))
    elif kind == "guidance":
        errors.extend(_validate_guidance(payload))
    elif kind == "revenue_driver":
        errors.extend(_validate_driver(payload))
    else:
        errors.append(f"unknown kind: {kind!r}")
    # The contract closes every variant with `additionalProperties: false`; the
    # checks above only look at the fields they know, so without this an invented
    # key rode through normalize, validate and persist untouched.
    errors.extend(_unknown_key_errors(payload))
    errors.extend(_evidence_control_field_errors(payload))
    return errors


def _require(payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [f"missing required field: {k}" for k in keys if k not in payload]


def _uuid_ok(value: Any) -> bool:
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _common(payload: dict[str, Any], *, reported: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("issuer_label"), str) or not payload["issuer_label"]:
        errors.append("issuer_label required")
    if not isinstance(payload.get("metric_id"), str) or not payload["metric_id"]:
        errors.append("metric_id required")
    if not isinstance(payload.get("raw_value"), str):
        errors.append("raw_value must be a string")
    if not _uuid_ok(payload.get("entity_id")):
        errors.append("entity_id must be a uuid")
    if payload.get("reported_or_derived") not in reported:
        errors.append(f"reported_or_derived must be one of {sorted(reported)}")
    errors.extend(_validate_period(payload.get("period")))
    dims = payload.get("dimensions")
    if not isinstance(dims, dict):
        errors.append("dimensions must be an object")
    elif any(not isinstance(v, str) for v in dims.values()):
        errors.append("dimensions values must be strings")
    quals = payload.get("qualifiers")
    if not isinstance(quals, dict):
        errors.append("qualifiers must be an object")
    return errors


def _validate_period(period: Any) -> list[str]:
    if not isinstance(period, dict):
        return ["period must be an object"]
    errors: list[str] = []
    ptype = period.get("type")
    if ptype not in _PERIOD_TYPES:
        errors.append(f"invalid period.type: {ptype!r}")
    return errors


def _numeric_trio(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("unit"), str) or not payload["unit"]:
        errors.append("unit required")
    currency = payload.get("currency")
    if currency is not None and (
        not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency)
    ):
        errors.append("currency must be null or ISO-4217 alpha-3")
    if not isinstance(payload.get("scale"), int) or isinstance(payload.get("scale"), bool):
        errors.append("scale must be an integer")
    if payload.get("sign") not in {"positive", "negative", "zero"}:
        errors.append("sign must be positive|negative|zero")
    return errors


def _decimal_field(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        return [f"{key} must be a decimal string"]
    return []


def _validate_numeric_shape(
    payload: dict[str, Any], *, required: tuple[str, ...], decimal_keys: tuple[str, ...]
) -> list[str]:
    errors = _require(payload, required)
    errors.extend(_numeric_trio(payload))
    for key in decimal_keys:
        errors.extend(_decimal_field(payload, key))
    return errors


def _validate_kpi(payload: dict[str, Any]) -> list[str]:
    errors = _require(payload, _KPI_REQUIRED)
    errors.extend(_common(payload, reported={"reported", "derived"}))
    errors.extend(_numeric_trio(payload))
    errors.extend(_decimal_field(payload, "value"))
    return errors


def _validate_guidance(payload: dict[str, Any]) -> list[str]:
    errors = _require(payload, _GUIDANCE_REQUIRED)
    errors.extend(_common(payload, reported={"management_assertion"}))
    shape = payload.get("shape")
    if shape == "point":
        errors.extend(
            _validate_numeric_shape(
                payload, required=("value", "unit", "scale", "sign"), decimal_keys=("value",)
            )
        )
    elif shape == "range":
        errors.extend(
            _validate_numeric_shape(
                payload,
                required=("low", "high", "unit", "scale", "sign"),
                decimal_keys=("low", "high"),
            )
        )
    elif shape == "floor":
        errors.extend(
            _validate_numeric_shape(
                payload, required=("low", "unit", "scale", "sign"), decimal_keys=("low",)
            )
        )
    elif shape == "ceiling":
        errors.extend(
            _validate_numeric_shape(
                payload, required=("high", "unit", "scale", "sign"), decimal_keys=("high",)
            )
        )
    elif shape == "qualitative":
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append("qualitative guidance requires text")
    else:
        errors.append(f"unknown guidance shape: {shape!r}")
    return errors


def _validate_driver(payload: dict[str, Any]) -> list[str]:
    errors = _require(payload, _DRIVER_REQUIRED)
    errors.extend(_common(payload, reported={"management_assertion"}))
    if payload.get("category") not in _DRIVER_CATEGORIES:
        errors.append(f"invalid category: {payload.get('category')!r}")
    if not isinstance(payload.get("description"), str) or not payload["description"]:
        errors.append("description required")
    if payload.get("direction") not in {"positive", "negative", "mixed", "unknown"}:
        errors.append("invalid direction")
    targets = payload.get("target_metric_ids")
    if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)):
        errors.append("target_metric_ids must be a non-empty unique array")
    return errors


__all__ = [
    "PIPELINE_CONTROL_EVIDENCE_KEYS",
    "WORKER_EXTENSION_KEYS",
    "allowed_payload_keys",
    "load_extraction_payload_schema",
    "validate_payload_item",
]
