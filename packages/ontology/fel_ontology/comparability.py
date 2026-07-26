"""Comparability keys: aliases never imply comparability."""

from __future__ import annotations

from fel_ontology.models import MetricDef


def build_comparability_key(metric: MetricDef, qualifiers: dict[str, str]) -> str:
    """Build a deterministic comparability key from required qualifier fields.

    Missing required qualifiers fail closed (KeyError) so callers cannot
    silently treat incomplete extractions as comparable.
    """
    parts: list[str] = []
    for field in metric.comparability_key_fields:
        if field == "metric_id":
            parts.append(f"metric_id={metric.id}")
            continue
        if field not in qualifiers or not str(qualifiers[field]).strip():
            raise KeyError(f"missing required qualifier for comparability: {field}")
        parts.append(f"{field}={qualifiers[field].strip()}")
    return "|".join(parts)


def metrics_comparable(
    left: MetricDef,
    left_qualifiers: dict[str, str],
    right: MetricDef,
    right_qualifiers: dict[str, str],
) -> bool:
    """True only when both sides share an identical comparability key."""
    return build_comparability_key(left, left_qualifiers) == build_comparability_key(
        right, right_qualifiers
    )
