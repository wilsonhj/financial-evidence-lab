"""Ontology definition / qualifier checks."""

from __future__ import annotations

from typing import Any

from fel_ontology.models import MetricDef, OntologyDocument

# The unit family each ontology ``value_type`` admits. Unit *strings* are never
# compared: the ontology writes ``USD/yr`` where a filing writes ``USD``, and a
# check that demanded equality would block every well-formed ARR payload.
_UNIT_BY_VALUE_TYPE = {"ratio_pct": "percent", "count": "count"}
_CURRENCY_VALUE_TYPES = frozenset({"currency", "currency_derived"})
# ``period_semantics`` values the ontology can express; ``forecast`` is a payload
# period type with no ontology counterpart, so it is never graded here.
_ONTOLOGY_PERIOD_TYPES = frozenset({"instant", "duration", "trailing_window"})


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


def check_definitions(payload: dict[str, Any], ontology: OntologyDocument) -> list[str]:
    """Cross-check a payload against the ontology definition of its metric.

    Until this was wired into ``validate/pipeline.py::_collect_blockers``,
    ``metric.unit``, ``metric.value_type`` and ``metric.period_semantics`` were
    read nowhere in the extraction path, so an ``arr`` denominated in percent
    with a null currency reached the review queue as ``ok: true, blockers: []``.

    Deliberately narrow. It grades only what the ontology states unambiguously,
    and it never second-guesses a metric it cannot resolve.

    It no longer restates required qualifiers: ``accounting_errors`` already
    emits ``missing required qualifier: <field>`` for the identical condition on
    the identical metrics, and ``_collect_blockers`` collapses only *exact*
    string repeats — so a second spelling of the same finding would reach a
    reviewer as two problems.
    """
    metric_id = payload.get("metric_id")
    if not isinstance(metric_id, str) or not metric_id:
        return ["metric_id_missing"]
    try:
        metric = ontology.metric(metric_id)
    except KeyError:
        # Same policy as `accounting_errors`: guidance and revenue_driver carry
        # free-text metric labels by design — the contract's own fixtures use
        # `revenue`, `gross_margin`, `churn`, `demand` and `price`, none of
        # which are SaaS-ontology metrics — so only a KPI must name a known one.
        return ["metric_unknown_to_ontology"] if payload.get("kind") == "kpi" else []
    blockers = _unit_errors(payload, metric)
    blockers.extend(_period_errors(payload, metric))
    return blockers


def _unit_errors(payload: dict[str, Any], metric: MetricDef) -> list[str]:
    """Unit and currency must be able to express the metric's ``value_type``.

    Skipped for a payload that declares no ``unit``: qualitative guidance and
    revenue drivers carry no numeric unit, and a numeric variant that omits one
    is already blocked by ``validate_payload_item``.
    """
    if "unit" not in payload:
        return []
    errors: list[str] = []
    unit = payload.get("unit")
    currency = payload.get("currency")
    expected = _UNIT_BY_VALUE_TYPE.get(metric.value_type)
    if expected is not None:
        if unit != expected:
            errors.append(
                f"unit {unit!r} cannot express {metric.value_type} metric "
                f"{metric.id} (expected {expected!r})"
            )
        if currency is not None:
            errors.append(
                f"{metric.id} is a {metric.value_type} metric and takes no "
                f"currency, got {currency!r}"
            )
    elif metric.value_type in _CURRENCY_VALUE_TYPES:
        if unit in set(_UNIT_BY_VALUE_TYPE.values()):
            errors.append(f"unit {unit!r} cannot express currency metric {metric.id}")
        if not isinstance(currency, str) or not currency:
            errors.append(f"currency metric {metric.id} declares no currency")
    return errors


def _period_errors(payload: dict[str, Any], metric: MetricDef) -> list[str]:
    """A reported KPI must be stated over the period shape its metric has.

    KPI only: guidance asserts a future period and a revenue driver carries no
    measurement window, so neither can be graded against ``period_semantics``.
    A ``forecast`` period type is likewise left alone — the ontology has no
    forecast semantics to compare it against.
    """
    if payload.get("kind") != "kpi":
        return []
    period = payload.get("period")
    ptype = period.get("type") if isinstance(period, dict) else None
    if ptype not in _ONTOLOGY_PERIOD_TYPES or ptype == metric.period_semantics:
        return []
    return [
        f"period.type {ptype!r} contradicts ontology period_semantics "
        f"{metric.period_semantics!r} for {metric.id}"
    ]


__all__ = ["check_definitions", "definition_errors"]
