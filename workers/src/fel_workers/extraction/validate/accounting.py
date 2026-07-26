"""Accounting identity checks (margins, billings, RPO, ontology ranges)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fel_ontology.models import OntologyDocument
from fel_workers.extraction.validate.range import check_range

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
    """Live-path accounting blockers used by ``validate_proposals``."""
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

    # Share Decimal low/high ordering with check_range; keep live-path messages.
    for code in check_range(payload):
        if code == "range_low_gt_high":
            errors.append("guidance range low must be <= high")
        elif code == "range_bounds_not_decimal":
            errors.append("guidance range low/high not decimal")
        else:
            errors.append(code)

    for field in metric.required_qualifiers:
        quals = payload.get("qualifiers") or {}
        if field not in quals or not str(quals.get(field, "")).strip():
            errors.append(f"missing required qualifier: {field}")
    return errors


def check_accounting(payload: dict[str, Any]) -> list[str]:
    """Lightweight metric-identity blockers (billings / margins / cRPO)."""
    blockers: list[str] = []
    metric_id = payload.get("metric_id")
    if metric_id == "billings":
        # Billings may only be derived with cited revenue + Δdeferred (enforced via evidence).
        if payload.get("reported_or_derived") == "derived":
            lineage = payload.get("qualifiers", {}).get("derivation_inputs")
            if not isinstance(lineage, list) or len(lineage) < 2:
                blockers.append("billings_derivation_inputs_missing")
    if metric_id == "svc_gm":
        # Never proxy blended margin.
        if payload.get("qualifiers", {}).get("basis") == "blended":
            blockers.append("svc_gm_blended_forbidden")
    if metric_id == "crpo":
        # cRPO needs timing dimension verification.
        dims = payload.get("dimensions") or {}
        if "horizon" not in dims and "timing_verified" not in (payload.get("qualifiers") or {}):
            blockers.append("crpo_timing_unverified")
    if metric_id in {"sub_gm", "svc_gm"} and "value" in payload:
        try:
            value = Decimal(str(payload["value"]))
            if value > 100 and payload.get("unit") == "percent":
                blockers.append("margin_percent_out_of_range")
        except (InvalidOperation, TypeError, ValueError):
            blockers.append("margin_value_invalid")
    return blockers


__all__ = ["accounting_errors", "check_accounting"]
