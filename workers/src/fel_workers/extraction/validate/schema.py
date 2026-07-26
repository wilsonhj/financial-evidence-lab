"""Frozen extraction-payload schema validation (stdlib; no network)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

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
    """Load the frozen contract schema (read-only reference)."""
    root = Path(__file__).resolve().parents[5]  # repo root via workers/src/...
    path = root / "packages" / "contracts" / "schemas" / "extraction-payload.schema.json"
    if not path.is_file():
        # Fallback: walk up looking for packages/contracts
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = (
                parent / "packages" / "contracts" / "schemas" / "extraction-payload.schema.json"
            )
            if candidate.is_file():
                path = candidate
                break
        else:
            raise FileNotFoundError("extraction-payload.schema.json not found")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError("extraction payload schema root must be an object")
    return loaded


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


__all__ = ["load_extraction_payload_schema", "validate_payload_item"]
