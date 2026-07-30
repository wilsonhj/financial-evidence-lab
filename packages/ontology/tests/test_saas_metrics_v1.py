"""Ontology load and field goldens for saas-metrics/v1."""

from __future__ import annotations

from pathlib import Path

import pytest

from fel_ontology.loader import EXPECTED_METRIC_IDS, OntologyLoadError, load_saas_metrics


def test_loads_exactly_fourteen_metrics_across_nine_families() -> None:
    doc = load_saas_metrics()
    assert doc.schema_version == "saas-metrics/v1"
    assert len(doc.metrics) == 14
    assert len(doc.families) == 9
    assert set(doc.metric_ids) == EXPECTED_METRIC_IDS
    assert doc.content_hash.startswith("sha256:")
    assert doc.limitations  # carried research limitations required


@pytest.mark.parametrize("metric_id", sorted(EXPECTED_METRIC_IDS))
def test_each_metric_has_required_contract_fields(metric_id: str) -> None:
    metric = load_saas_metrics().metric(metric_id)
    assert metric.aliases
    assert metric.value_type
    assert metric.unit
    assert metric.period_semantics
    assert metric.required_qualifiers
    assert metric.comparability_key_fields
    assert "metric_id" in metric.comparability_key_fields
    assert metric.derivation_policy
    assert metric.review_policy


def test_svc_gm_never_proxies_blended_margin() -> None:
    svc = load_saas_metrics().metric("svc_gm")
    assert "never proxy blended" in svc.notes.lower()
    assert svc.id != "sub_gm"


def test_rpo_and_crpo_are_distinct_comparability_families() -> None:
    doc = load_saas_metrics()
    rpo = doc.metric("rpo")
    crpo = doc.metric("crpo")
    assert rpo.comparability_key_fields != crpo.comparability_key_fields
    assert rpo.id != crpo.id


def test_corrupt_metric_set_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"schema_version":"saas-metrics/v1","ontology_id":"saas-metrics",'
        '"limitations":[],"families":[],"metrics":[]}',
        encoding="utf-8",
    )
    with pytest.raises(OntologyLoadError):
        load_saas_metrics(path=str(path))
