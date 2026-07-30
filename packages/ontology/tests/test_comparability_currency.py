"""Comparability keys must be buildable, and must never merge currencies.

Two invariants that the metric contract itself has to satisfy:

1. Every ``comparability_key_fields`` entry is either ``metric_id`` or a
   ``required_qualifiers`` entry, so a conformant extraction can always build
   the key. A key field that is not required can never be supplied, so
   ``build_comparability_key`` fails closed forever and the ontology
   comparability gate silently degrades to "unavailable" for that metric.
2. Currency scopes a monetary comparability key. The same metric, period and
   entity reported in USD and in JPY is not one figure disagreeing with
   itself.
"""

from __future__ import annotations

import pytest

from fel_ontology import build_comparability_key, load_saas_metrics, metrics_comparable
from fel_ontology.loader import EXPECTED_METRIC_IDS


def _required_only(metric) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Qualifiers a fully conformant extraction is guaranteed to carry."""
    return {name: f"<{name}>" for name in metric.required_qualifiers}


def _currency_metric_ids() -> list[str]:
    doc = load_saas_metrics()
    return sorted(m.id for m in doc.metrics if "currency" in m.required_qualifiers)


@pytest.mark.parametrize("metric_id", sorted(EXPECTED_METRIC_IDS))
def test_key_fields_are_all_required_qualifiers(metric_id: str) -> None:
    metric = load_saas_metrics().metric(metric_id)
    unsatisfiable = [
        field
        for field in metric.comparability_key_fields
        if field != "metric_id" and field not in metric.required_qualifiers
    ]
    assert not unsatisfiable, (
        f"{metric_id} keys on {unsatisfiable} but never requires them: "
        "the comparability key can never be built"
    )


@pytest.mark.parametrize("metric_id", sorted(EXPECTED_METRIC_IDS))
def test_key_builds_from_required_qualifiers_alone(metric_id: str) -> None:
    metric = load_saas_metrics().metric(metric_id)
    key = build_comparability_key(metric, _required_only(metric))
    assert key.startswith(f"metric_id={metric_id}")


@pytest.mark.parametrize("metric_id", _currency_metric_ids())
def test_currency_is_part_of_the_comparability_key(metric_id: str) -> None:
    metric = load_saas_metrics().metric(metric_id)
    assert "currency" in metric.comparability_key_fields


@pytest.mark.parametrize("metric_id", _currency_metric_ids())
def test_usd_and_jpy_do_not_share_a_comparability_key(metric_id: str) -> None:
    metric = load_saas_metrics().metric(metric_id)
    usd = {**_required_only(metric), "currency": "USD"}
    jpy = {**_required_only(metric), "currency": "JPY"}
    assert build_comparability_key(metric, usd) != build_comparability_key(metric, jpy)
    assert not metrics_comparable(metric, usd, metric, jpy)


@pytest.mark.parametrize("metric_id", _currency_metric_ids())
def test_missing_currency_still_fails_closed(metric_id: str) -> None:
    metric = load_saas_metrics().metric(metric_id)
    quals = _required_only(metric)
    quals.pop("currency")
    with pytest.raises(KeyError):
        build_comparability_key(metric, quals)
