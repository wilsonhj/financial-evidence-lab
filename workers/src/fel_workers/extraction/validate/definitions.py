"""Ontology definition / qualifier checks."""

from __future__ import annotations

from typing import Any

from fel_ontology import load_saas_metrics
from fel_ontology.loader import OntologyLoadError
from fel_ontology.models import OntologyDocument

_FALLBACK_KNOWN_METRICS = frozenset(
    {
        "arr",
        "mrr",
        "nrr",
        "grr",
        "cust_total",
        "cust_threshold",
        "seats",
        "bookings",
        "billings",
        "rpo",
        "crpo",
        "deferred_rev",
        "sub_gm",
        "svc_gm",
        "revenue",
        "gross_margin",
        "churn",
        "demand",
        "price",
    }
)


def definition_errors(payload: dict[str, Any], ontology: OntologyDocument) -> list[str]:
    """Soft definition-vs-alias collision check for the live validate path."""
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
    text = str(definition).lower().strip()
    for other in ontology.metrics:
        if other.id == metric.id:
            continue
        for alias in other.aliases:
            if alias.lower() == text:
                return [f"definition text collides with alias of {other.id}"]
    return []


def check_definitions(payload: dict[str, Any]) -> list[str]:
    """Required-qualifier blockers when ontology lookup is available."""
    blockers: list[str] = []
    metric_id = payload.get("metric_id")
    if not isinstance(metric_id, str) or not metric_id:
        return ["metric_id_missing"]
    metric = _lookup_metric(metric_id)
    if metric is None:
        # Unknown metrics still proceed to review with a blocker (fail-closed for approval).
        blockers.append("metric_unknown_to_ontology")
        return blockers
    required = metric.get("required_qualifiers") or []
    qualifiers = payload.get("qualifiers") or {}
    for name in required:
        if name not in qualifiers:
            blockers.append(f"qualifier_missing:{name}")
    return blockers


def _lookup_metric(metric_id: str) -> dict[str, Any] | None:
    try:
        doc = load_saas_metrics()
        metric = doc.metric(metric_id)
        return {
            "id": metric.id,
            "required_qualifiers": list(metric.required_qualifiers),
        }
    except KeyError:
        return None
    except OntologyLoadError:
        if metric_id in _FALLBACK_KNOWN_METRICS:
            return {"id": metric_id, "required_qualifiers": []}
        return None


__all__ = ["check_definitions", "definition_errors"]
