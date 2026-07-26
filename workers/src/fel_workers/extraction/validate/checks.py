"""Accounting / range / definition / citation / conflict validators."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fel_ontology import load_saas_metrics
from fel_ontology.models import OntologyDocument
from fel_workers.extraction.hashing import hash_json, sha256_hex
from fel_workers.extraction.validate.schema import validate_payload_item

# svc_gm must never be treated as blended company gross margin.
_BLENDED_MARGIN_MARKERS = frozenset(
    {
        "blended",
        "company",
        "consolidated",
        "total_gm",
        "total_gross_margin",
        "blended_margin",
    }
)


def accounting_errors(payload: dict[str, Any], ontology: OntologyDocument) -> list[str]:
    errors: list[str] = []
    metric_id = payload.get("metric_id")
    if not isinstance(metric_id, str):
        return ["metric_id missing"]
    try:
        metric = ontology.metric(metric_id)
    except KeyError:
        # Unknown metrics are allowed for guidance/driver free-text IDs but flagged.
        if payload.get("kind") == "kpi":
            errors.append(f"unknown ontology metric_id: {metric_id}")
        return errors

    if metric_id == "svc_gm":
        scope = str((payload.get("qualifiers") or {}).get("margin_scope", "")).lower()
        if any(marker in scope for marker in _BLENDED_MARGIN_MARKERS) or scope in {
            "blended",
            "company",
            "consolidated",
        }:
            errors.append("svc_gm must never proxy blended company gross margin")
        if "blended" in str(payload.get("definition") or "").lower():
            errors.append("svc_gm definition must not claim blended margin")

    if payload.get("kind") == "kpi" and metric.value_type == "ratio_pct":
        try:
            value = Decimal(str(payload.get("value")))
        except (InvalidOperation, TypeError):
            errors.append("kpi value is not a decimal")
        else:
            # Ratios expressed as percent points commonly 0–200; soft range flag.
            if value < Decimal("-100") or value > Decimal("500"):
                errors.append(f"ratio percent out of plausible range: {value}")

    if payload.get("kind") == "guidance" and payload.get("shape") == "range":
        try:
            low = Decimal(str(payload["low"]))
            high = Decimal(str(payload["high"]))
        except (InvalidOperation, KeyError, TypeError):
            errors.append("guidance range low/high not decimal")
        else:
            if low > high:
                errors.append("guidance range low must be <= high")

    for field in metric.required_qualifiers:
        quals = payload.get("qualifiers") or {}
        if field not in quals or not str(quals.get(field, "")).strip():
            errors.append(f"missing required qualifier: {field}")
    return errors


def range_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("value", "low", "high"):
        if key not in payload:
            continue
        try:
            Decimal(str(payload[key]))
        except (InvalidOperation, TypeError):
            errors.append(f"{key} is not a decimal string")
    scale = payload.get("scale")
    if scale is not None and (not isinstance(scale, int) or isinstance(scale, bool)):
        errors.append("scale must be int")
    elif isinstance(scale, int) and (scale < 0 or scale > 12):
        errors.append(f"scale out of range: {scale}")
    return errors


def definition_errors(payload: dict[str, Any], ontology: OntologyDocument) -> list[str]:
    metric_id = payload.get("metric_id")
    if not isinstance(metric_id, str):
        return []
    try:
        metric = ontology.metric(metric_id)
    except KeyError:
        return []
    definition = payload.get("definition")
    if definition is None:
        return []
    text = str(definition).lower()
    # Soft check: if issuer definition clearly aliases a different family metric.
    for other in ontology.metrics:
        if other.id == metric.id:
            continue
        for alias in other.aliases:
            if alias.lower() == text.strip():
                return [f"definition text collides with alias of {other.id}"]
    return []


def citation_errors(
    payload: dict[str, Any],
    *,
    evidence_by_span: dict[str, dict[str, Any]],
    expected_hashes: dict[str, str] | None = None,
) -> list[str]:
    """Verify cited span ids exist and optional text hashes match."""
    errors: list[str] = []
    evidence = payload.get("evidence") or payload.get("source_span_ids") or []
    span_ids: list[str] = []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, str):
                span_ids.append(item)
            elif isinstance(item, dict) and item.get("source_span_id"):
                span_ids.append(str(item["source_span_id"]))
    # Evidence may also live beside the payload in a draft; optional.
    for span_id in span_ids:
        block = evidence_by_span.get(span_id)
        if block is None:
            errors.append(f"cited span not in pinned evidence: {span_id}")
            continue
        if expected_hashes and span_id in expected_hashes:
            actual = block.get("text_hash") or sha256_hex(block.get("text", ""))
            if actual != expected_hashes[span_id]:
                errors.append(f"span hash mismatch: {span_id}")
    return errors


def duplicate_groups(payloads: list[dict[str, Any]]) -> list[list[int]]:
    """Group indices that share kind+metric_id+period+value fingerprint."""
    buckets: dict[str, list[int]] = {}
    for idx, payload in enumerate(payloads):
        key = hash_json(
            {
                "kind": payload.get("kind"),
                "metric_id": payload.get("metric_id"),
                "period": payload.get("period"),
                "value": payload.get("value"),
                "low": payload.get("low"),
                "high": payload.get("high"),
                "category": payload.get("category"),
            }
        )
        buckets.setdefault(key, []).append(idx)
    return [members for members in buckets.values() if len(members) > 1]


def conflict_key_for(payload: dict[str, Any]) -> str:
    """Deterministic conflict grouping key (same metric/period, differing values)."""
    return hash_json(
        {
            "kind": payload.get("kind"),
            "metric_id": payload.get("metric_id"),
            "period": payload.get("period"),
            "dimensions": payload.get("dimensions") or {},
        }
    )


def value_fingerprint(payload: dict[str, Any]) -> str:
    return hash_json(
        {
            "value": payload.get("value"),
            "low": payload.get("low"),
            "high": payload.get("high"),
            "text": payload.get("text"),
            "category": payload.get("category"),
            "direction": payload.get("direction"),
            "raw_value": payload.get("raw_value"),
        }
    )


def default_ontology() -> OntologyDocument:
    return load_saas_metrics()


__all__ = [
    "accounting_errors",
    "citation_errors",
    "conflict_key_for",
    "default_ontology",
    "definition_errors",
    "duplicate_groups",
    "range_errors",
    "validate_payload_item",
    "value_fingerprint",
]
