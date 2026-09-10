"""Signed numeric bounds and conservative repair under ADR-0022 (#154)."""

from copy import deepcopy
from decimal import Decimal

import pytest

from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.normalize import normalize_payload
from fel_workers.extraction.types import NORMALIZER_BLOCKERS_KEY
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.duplicates import (
    comparability_key_for,
    conflict_key_for,
    value_fingerprint,
)
from fel_workers.extraction.validate.range import check_range, range_errors

from .test_accounting_identities import DURATION, kpi
from .test_confidence_and_priority import _PINNED

ORDERING = "guidance range low must be <= high"


def guidance(low="(5)", high="(15)", *, metric="svc_gm", **overrides):
    payload = kpi(
        metric,
        "0",
        kind="guidance",
        shape="range",
        low=low,
        high=high,
        sign=None,
        unit="percent" if metric == "svc_gm" else "USD",
        currency=None if metric == "svc_gm" else "USD",
        period=DURATION,
        raw_value=f"Issuer expects {low} to {high} next quarter.",
        qualifiers={"basis": "gaap", "margin_scope": "services"},
    )
    payload.pop("value")
    for row in payload["evidence"]:
        row["text_hash"] = _PINNED[row["source_span_id"]]["text_hash"]
    payload.update(overrides)
    return payload


def validate(payloads):
    return validate_proposals(run_id="fixed-run", payloads=payloads, evidence_by_span=_PINNED)


@pytest.mark.parametrize("metric", ["svc_gm", "revenue"])
@pytest.mark.parametrize(
    "low,high,expected,blocked",
    [
        ("(5)", "(15)", ("-15", "-5"), False),
        ("(15)", "(5)", ("-15", "-5"), False),
        ("-5", "-15", ("-15", "-5"), False),
        ("-15", "-5", ("-15", "-5"), False),
        ("(5)", "(5)", ("-5", "-5"), False),
        ("120", "125", ("120", "125"), False),
        ("300", "200", ("300", "200"), True),
        ("-5", "5", ("-5", "5"), False),
        ("5", "-5", ("5", "-5"), True),
        ("-5", "0", ("-5", "0"), False),
        ("0", "-5", ("0", "-5"), True),
    ],
)
def test_source_order_matrix(metric, low, high, expected, blocked):
    source = guidance(low, high, metric=metric)
    before = deepcopy(source)
    normalized = normalize_payload(source)
    assert (normalized["low"], normalized["high"]) == expected
    assert source == before
    assert normalized["raw_value"] == source["raw_value"]
    assert normalize_payload(normalized) == normalized
    draft = validate([normalized]).proposals[0]
    assert draft.validation_summary["blockers"].count(ORDERING) == int(blocked)
    if blocked:
        assert draft.review_priority == "high"
    if metric == "svc_gm" and max(map(Decimal, expected)) <= 100 and not blocked:
        assert draft.validation_summary["ok"], draft.validation_summary
        assert draft.review_priority == "normal"


@pytest.mark.parametrize("metric", ["revenue", "operating_income", "net_loss", "svc_gm"])
def test_validator_is_strict_independently_of_ontology(metric):
    raw = guidance("-5", "-15", metric=metric)
    assert check_range(raw) == ["range_low_gt_high"]
    assert range_errors(raw) == [ORDERING]
    assert validate([raw]).proposals[0].validation_summary["blockers"].count(ORDERING) == 1
    positive = normalize_payload(guidance("300", "200", metric=metric))
    assert (positive["low"], positive["high"]) == ("300", "200")
    assert validate([positive]).proposals[0].validation_summary["blockers"].count(ORDERING) == 1


@pytest.mark.parametrize("bound", [None, "not a number", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_invalid_bounds_fail_closed(bound):
    raw = guidance(low="-5", high=bound)
    assert check_range(raw) == ["range_bounds_not_decimal"]
    assert "guidance range low/high not decimal" in range_errors(raw)
    assert not validate([raw]).proposals[0].validation_summary["ok"]


def test_missing_bound_remains_rejected():
    raw = guidance()
    raw.pop("high")
    with pytest.raises(ValueError, match="missing numeric field high"):
        normalize_payload(raw)
    assert check_range(raw) == ["range_bounds_not_decimal"]
    assert "guidance range low/high not decimal" in range_errors(raw)


def test_scale_reconciliation_precedes_signed_ordering():
    raw = guidance("(900 million)", "(1.2 billion)", metric="net_loss", unit="usd", scale=6)
    out = normalize_payload(raw)
    assert (out["low"], out["high"], out["scale"]) == ("-1200", "-900", 6)
    assert out["raw_value"] == raw["raw_value"]
    assert out["unit"] == "usd"
    assert sorted(Decimal(out[k]).scaleb(out["scale"]) for k in ("low", "high")) == [
        Decimal("-1200000000"),
        Decimal("-900000000"),
    ]
    assert normalize_payload(out) == out


@pytest.mark.parametrize("scale", [99, -3, True, "6"])
def test_invalid_scale_survives_order_repair(scale):
    out = normalize_payload(guidance(scale=scale))
    assert out["scale"] == scale
    assert out[NORMALIZER_BLOCKERS_KEY]
    assert normalize_payload(out) == out
    assert not validate([out]).proposals[0].validation_summary["ok"]


@pytest.mark.parametrize("sign", ["positive", "malformed"])
def test_declared_sign_blocker_survives_swap_and_second_normalization(sign):
    out = normalize_payload(guidance(sign=sign))
    assert (out["low"], out["high"], out["sign"]) == ("-15", "-5", "negative")
    assert any("sign" in b for b in out[NORMALIZER_BLOCKERS_KEY])
    assert normalize_payload(out) == out
    assert not validate([out]).proposals[0].validation_summary["ok"]


@pytest.mark.parametrize("shape,key", [("point", "value"), ("floor", "low"), ("ceiling", "high")])
def test_other_numeric_shapes_retain_bound_meaning(shape, key):
    raw = guidance(shape=shape)
    raw.pop("low")
    raw.pop("high")
    raw[key] = "(5)"
    out = normalize_payload(raw)
    assert out[key] == "-5"
    assert out["shape"] == shape
    assert set(out) & {"value", "low", "high"} == {key}
    assert check_range(out) == []


def test_qualitative_shape_has_no_numeric_repair():
    raw = guidance(shape="qualitative", text="Loss expected to narrow")
    for key in ("low", "high", "sign", "scale", "currency", "unit"):
        raw.pop(key)
    assert normalize_payload(raw)["text"] == raw["text"]
    assert check_range(raw) == []


def test_opposite_source_orders_are_duplicates_with_distinct_source_hashes():
    payloads = [normalize_payload(guidance(a, b)) for a, b in [("(5)", "(15)"), ("(15)", "(5)")]]
    assert value_fingerprint(payloads[0]) == value_fingerprint(payloads[1])
    result = validate(payloads)
    assert all("duplicate_candidate" in p.validation_summary["blockers"] for p in result.proposals)
    assert not any("value_disagreement" in c.reason_codes for c in result.conflicts)
    assert result.proposals[0].raw_payload_hash != result.proposals[1].raw_payload_hash
    assert result.proposals[0].id != result.proposals[1].id
    different = validate([payloads[0], normalize_payload(guidance("(5)", "(20)"))])
    assert any("value_disagreement" in c.reason_codes for c in different.conflicts)


@pytest.mark.parametrize(
    "changes", [{"currency": "EUR"}, {"unit": "USD/yr"}, {"dimensions": {"segment": "other"}}]
)
def test_range_repair_does_not_merge_distinct_slices(changes):
    first = normalize_payload(guidance(metric="net_loss"))
    other = normalize_payload(guidance(metric="net_loss", **changes))
    assert validate([first, other]).conflicts == []
    assert comparability_key_for(first) != comparability_key_for(other)


def test_all_conflict_shapes_receive_both_policy_namespaces():
    from fel_workers.extraction.types import RANGE_POLICY_VERSION

    for payload in [guidance(), guidance(shape="point"), kpi("revenue", "100")]:
        identity = comparability_key_for(payload)
        legacy = {"unit_policy_version": "unit-comparison/v1", "identity": identity}
        assert conflict_key_for(payload) != hash_json(legacy)
        assert conflict_key_for(payload) == hash_json(
            {**legacy, "range_policy_version": RANGE_POLICY_VERSION}
        )
