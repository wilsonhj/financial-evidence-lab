"""PR #75 Part 2b definitional conflicts → distinct comparability keys."""

from __future__ import annotations

import pytest

from fel_ontology import build_comparability_key, load_saas_metrics, metrics_comparable


@pytest.fixture(scope="module")
def ontology():  # type: ignore[no-untyped-def]
    return load_saas_metrics()


def test_nrr_arr_base_vs_product_revenue_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    nrr = ontology.metric("nrr")
    left = {"base_quantity": "arr", "window": "ttm_point_in_time", "population_scope": "all"}
    right = {
        "base_quantity": "product_revenue",
        "window": "year_over_year_cohort",
        "population_scope": "all",
    }
    assert build_comparability_key(nrr, left) != build_comparability_key(nrr, right)
    assert not metrics_comparable(nrr, left, nrr, right)


def test_nrr_arr_vs_acv_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    nrr = ontology.metric("nrr")
    left = {"base_quantity": "arr", "window": "ttm_point_in_time", "population_scope": "all"}
    right = {"base_quantity": "acv", "window": "ttm_point_in_time", "population_scope": "all"}
    assert not metrics_comparable(nrr, left, nrr, right)


def test_nrr_window_averaging_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    nrr = ontology.metric("nrr")
    left = {
        "base_quantity": "arr",
        "window": "weighted_avg_trailing_12m_point_in_time",
        "population_scope": "all",
    }
    right = {
        "base_quantity": "arr",
        "window": "avg_quarterly_net_expansion",
        "population_scope": "all",
    }
    assert not metrics_comparable(nrr, left, nrr, right)


def test_nrr_enterprise_vs_all_customers_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    nrr = ontology.metric("nrr")
    left = {
        "base_quantity": "arr",
        "window": "ttm_point_in_time",
        "population_scope": "enterprise",
    }
    right = {"base_quantity": "arr", "window": "ttm_point_in_time", "population_scope": "all"}
    assert not metrics_comparable(nrr, left, nrr, right)


def test_alias_match_does_not_imply_comparability(ontology) -> None:  # type: ignore[no-untyped-def]
    """NRR aliases include expansion names; qualifier keys still decide comparability."""
    nrr = ontology.metric("nrr")
    assert "net expansion rate" in {a.lower() for a in nrr.aliases}
    left = {
        "base_quantity": "arr",
        "window": "ttm_point_in_time",
        "population_scope": "all",
    }
    right = {
        "base_quantity": "recognized_revenue",
        "window": "quarterly_avg",
        "population_scope": "all",
    }
    assert not metrics_comparable(nrr, left, nrr, right)


def test_cust_threshold_arr_vs_ttm_revenue_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    metric = ontology.metric("cust_threshold")
    left = {"threshold_amount": "100000", "threshold_basis": "arr"}
    right = {"threshold_amount": "100000", "threshold_basis": "ttm_revenue"}
    assert not metrics_comparable(metric, left, metric, right)


def test_cust_threshold_acv_vs_arr_and_cutoff_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    metric = ontology.metric("cust_threshold")
    left = {"threshold_amount": "5000000", "threshold_basis": "acv"}
    right = {"threshold_amount": "100000", "threshold_basis": "arr"}
    assert not metrics_comparable(metric, left, metric, right)


def test_arr_mrr_times_12_vs_acv_construction_not_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    arr = ontology.metric("arr")
    left = {"currency": "USD", "construction": "mrr_x_12", "scope": "all"}
    right = {"currency": "USD", "construction": "annualized_contract_value", "scope": "all"}
    assert not metrics_comparable(arr, left, arr, right)


def test_rpo_vs_subscription_backlog_label_still_needs_exemption_key(
    ontology,
) -> None:  # type: ignore[no-untyped-def]
    rpo = ontology.metric("rpo")
    assert "subscription revenue backlog" in {a.lower() for a in rpo.aliases}
    left = {
        "currency": "USD",
        "usage_exemption": "none",
        "label_family": "rpo",
    }
    right = {
        "currency": "USD",
        "usage_exemption": "usage_and_lt_one_year_exempt",
        "label_family": "subscription_revenue_backlog",
    }
    assert not metrics_comparable(rpo, left, rpo, right)


def test_billings_formula_qualifier_required(ontology) -> None:  # type: ignore[no-untyped-def]
    billings = ontology.metric("billings")
    with pytest.raises(KeyError):
        build_comparability_key(billings, {"currency": "USD"})
    key = build_comparability_key(
        billings, {"currency": "USD", "formula": "revenue_plus_delta_deferred"}
    )
    assert "formula=revenue_plus_delta_deferred" in key


def test_identical_qualifiers_are_comparable(ontology) -> None:  # type: ignore[no-untyped-def]
    nrr = ontology.metric("nrr")
    q = {"base_quantity": "arr", "window": "ttm_point_in_time", "population_scope": "all"}
    assert metrics_comparable(nrr, q, nrr, q)
