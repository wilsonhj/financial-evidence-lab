"""ADR-0019 comparison semantics must agree across every validator."""

from copy import deepcopy

import pytest

from fel_workers.extraction.normalize.currency import normalize_currency
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.accounting import identity_errors
from fel_workers.extraction.validate.duplicates import comparability_key_for, duplicate_groups

from .test_accounting_identities import kpi


@pytest.mark.parametrize(
    "metric,values,dimensions",
    [
        (("revenue", "cogs", "gross_profit"), ("1000", "300", "600"), ({}, {}, {})),
        (("rpo", "crpo"), ("500", "900"), ({}, {})),
        (("arr", "arr", "arr"), ("1000", "400", "300"), ({}, {"segment": "a"}, {"segment": "b"})),
    ],
)
def test_all_identities_compare_case_aliases(metric, values, dimensions):
    payloads = [
        kpi(m, v, unit=("USD" if i == 0 else "usd"), dimensions=d)
        for i, (m, v, d) in enumerate(zip(metric, values, dimensions, strict=True))
    ]
    assert set(identity_errors(payloads)) == set(range(len(payloads)))


@pytest.mark.parametrize("value,duplicate", [("1000", True), ("900", False)])
def test_case_ambiguity_is_detected(value, duplicate):
    payloads = [kpi("revenue", "1000"), kpi("revenue", value, unit="usd")]
    result = validate_proposals(run_id="unit-policy-test", payloads=payloads)
    assert bool(duplicate_groups(payloads)) is duplicate
    assert (
        all("duplicate_candidate" in p.validation_summary["blockers"] for p in result.proposals)
        is duplicate
    )
    if not duplicate:
        assert any("value_disagreement" in c.reason_codes for c in result.conflicts)


@pytest.mark.parametrize(
    "left,right",
    [
        ("CPU", "cpu"),
        ("ss", "ß"),
        ("k", "K"),
        ("I", "ı"),
        ("I", "İ"),
        ("USD/mo", "USD/yr"),
        ("USD/mo", "usd/Mo"),
        ("percent", "pp"),
        ("pure", "ratio"),
        ("shares", "customers"),
    ],
)
def test_unknown_units_and_distinct_families_never_merge(left, right):
    payloads = [kpi("revenue", "1000", unit=u) for u in (left, right)]
    assert comparability_key_for(payloads[0]) != comparability_key_for(payloads[1])
    assert duplicate_groups(payloads) == []
    payloads[1]["value"] = "900"
    assert validate_proposals(run_id="unit-policy-test", payloads=payloads).conflicts == []


@pytest.mark.parametrize("unit", ["usd", "usd/yr", "Currency", "Currency/mo", "chf", "sek", "inr"])
def test_lowercase_money_needs_declared_currency(unit):
    assert normalize_currency(currency=None, unit=unit) == (None, ["currency_missing_for_monetary"])


def test_unknown_three_letter_unit_is_not_currency():
    assert normalize_currency(currency=None, unit="CPU") == (None, [])
    with pytest.raises(ValueError):
        normalize_currency(currency="usd", unit="USD")


def test_comparisons_preserve_payload():
    payload = kpi("revenue", "1000", unit="usd")
    before = deepcopy(payload)
    result = validate_proposals(run_id="unit-policy-test", payloads=[payload])
    assert payload == before
    assert result.proposals[0].payload["unit"] == "usd"


@pytest.mark.parametrize("unit", ["Percent", "PERCENT", "%", "pct", "percentage"])
def test_definition_and_plausibility_share_percent_aliases(unit):
    from fel_ontology import load_saas_metrics
    from fel_workers.extraction.validate.accounting import accounting_errors
    from fel_workers.extraction.validate.definitions import check_definitions

    payload = kpi("sub_gm", "110", unit=unit, currency=None)
    assert not any("unit " in b for b in check_definitions(payload, load_saas_metrics()))
    assert "margin_percent_out_of_range" in accounting_errors(payload, load_saas_metrics())
    assert duplicate_groups([payload, dict(payload, unit="percent")]) == [[0, 1]]


@pytest.mark.parametrize("unit", ["pure", "ratio", "shares", "customers", "unknown"])
def test_currency_family_does_not_acquire_unrelated_restrictions(unit):
    from fel_ontology import load_saas_metrics
    from fel_workers.extraction.validate.definitions import check_definitions

    assert not any(
        "unit " in b for b in check_definitions(kpi("arr", "100", unit=unit), load_saas_metrics())
    )


def test_withheld_mixed_case_segment_suppresses_partial_sum():
    payloads = [
        kpi("arr", "100"),
        kpi("arr", "50", unit="usd", dimensions={"segment": "a"}),
        kpi("arr", "30", dimensions={"segment": "b"}),
        kpi("arr", "20", unit="Usd", dimensions={"segment": "c"}),
    ]
    assert identity_errors(payloads, excluded_indices=frozenset({3})) == {}


def test_new_conflict_namespace_and_unchanged_proposal_algorithm():
    from fel_ontology.units import UNIT_POLICY_VERSION
    from fel_workers.extraction.hashing import hash_json, proposal_id_for
    from fel_workers.extraction.validate.duplicates import conflict_key_for

    payload = kpi("revenue", "1000", unit="usd")
    draft = validate_proposals(
        run_id="fixed-run", payloads=[dict(payload, _metadata="ignored")]
    ).proposals[0]
    assert draft.raw_payload_hash == hash_json(payload)
    assert draft.id == proposal_id_for(
        run_id="fixed-run", kind="kpi", metric_id="revenue", raw_payload_hash=hash_json(payload)
    )
    assert draft.validation_summary["unit_policy_version"] == UNIT_POLICY_VERSION
    identity = comparability_key_for(payload)
    assert conflict_key_for(payload) == hash_json(
        {"unit_policy_version": UNIT_POLICY_VERSION, "identity": identity}
    )
    assert conflict_key_for(payload) != hash_json(identity)
    assert conflict_key_for(payload) == conflict_key_for(dict(payload, unit="USD"))
    assert (
        draft.id
        != validate_proposals(run_id="fixed-run", payloads=[dict(payload, unit="USD")])
        .proposals[0]
        .id
    )
