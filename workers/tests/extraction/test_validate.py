"""Validator + conflict grouping tests (M3-106)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fel_ontology import load_saas_metrics
from fel_workers.extraction.types import ProposalDraft
from fel_workers.extraction.validate import validate_payload_item, validate_proposals
from fel_workers.extraction.validate.checks import accounting_errors
from fel_workers.extraction.validate.duplicates import (
    canonical_magnitude,
    comparability_key_for,
    conflict_key_for,
    duplicate_groups,
    value_fingerprint,
)

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)

_OTHER_ENTITY = "11111111-1111-4111-8111-111111111112"


def _arr(**overrides: Any) -> dict[str, Any]:
    """A schema-valid ARR payload whose qualifiers build a comparability key."""
    payload = dict(json.loads(FIXTURES.read_text(encoding="utf-8"))["kpi"])
    payload["qualifiers"] = {
        "currency": "USD",
        "construction": "reported_arr",
        "scope": "consolidated",
    }
    payload.update(overrides)
    return payload


def _blockers(draft: ProposalDraft) -> list[str]:
    return [str(b) for b in draft.validation_summary.get("blockers") or []]


def test_contract_fixtures_schema_valid() -> None:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for key, payload in data.items():
        if key == "note" or not isinstance(payload, dict):
            continue
        assert validate_payload_item(payload) == [], key


def test_svc_gm_never_proxies_blended_margin() -> None:
    ontology = load_saas_metrics()
    payload = {
        "kind": "kpi",
        "metric_id": "svc_gm",
        "value": "10",
        "qualifiers": {"margin_scope": "blended company"},
        "definition": "blended gross margin",
    }
    errors = accounting_errors(payload, ontology)
    assert any("never proxy blended" in e for e in errors)


def test_proposals_always_needs_review() -> None:
    result = validate_proposals(run_id="00000000-0000-4000-8000-000000000001", payloads=[_arr()])
    assert result.proposals
    assert all(p.state == "needs_review" for p in result.proposals)


def test_conflict_groups_deterministic() -> None:
    left = _arr()
    right = _arr(value="200", raw_value="$200 million")
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000002",
        payloads=[left, right],
    )
    assert len(result.conflicts) == 1
    assert len(result.conflicts[0].member_proposal_ids) == 2


# --- value_fingerprint must normalize the mantissa + scale-exponent pair ------


def test_canonical_magnitude_is_scale_independent() -> None:
    """`{"value": "1.2", "scale": 9}` and `{"value": "1200", "scale": 6}` are $1.2bn."""
    assert canonical_magnitude("1.2", 9) == canonical_magnitude("1200", 6)
    assert canonical_magnitude("1200", 6) == canonical_magnitude("1200000", 3)
    # Zero is one amount at every scale and carries no sign.
    assert canonical_magnitude("0", 6) == canonical_magnitude("-0.00", 0)
    # A genuinely different magnitude still reduces to a different token.
    assert canonical_magnitude("1.2", 9) != canonical_magnitude("1.2", 6)
    assert canonical_magnitude("1.2", 9) != canonical_magnitude("1.3", 9)
    assert canonical_magnitude("100", 6) != canonical_magnitude("-100", 6)


def test_canonical_magnitude_handles_absent_and_unparseable_input() -> None:
    assert canonical_magnitude(None, 6) is None
    # A missing scale shifts nothing rather than guessing a magnitude.
    assert canonical_magnitude("100", None) == canonical_magnitude("100", 0)
    # A negative exponent is out of the validator's plausible range but must
    # still reduce exactly rather than reach float math.
    assert canonical_magnitude("1.5", -2) == canonical_magnitude("0.015", 0)
    # Unparseable values stay distinct instead of collapsing on a placeholder.
    assert canonical_magnitude("n/a", 6) != canonical_magnitude("tbd", 6)


def test_billions_and_millions_are_one_amount_not_a_disagreement() -> None:
    """$1.2bn and $1,200m are the same figure restated, not two figures."""
    billions = _arr(raw_value="$1.2 billion", value="1.2", scale=9)
    millions = _arr(raw_value="$1,200 million", value="1200", scale=6)
    assert value_fingerprint(billions) == value_fingerprint(millions)

    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000003",
        payloads=[billions, millions],
    )
    assert len(result.proposals) == 2
    assert not any("value_disagreement" in c.reason_codes for c in result.conflicts)
    # They are one figure reported twice, so they are a duplicate candidate.
    assert duplicate_groups([billions, millions]) == [[0, 1]]
    assert all(p.validation_summary["duplicate"] for p in result.proposals)


def test_range_bounds_are_normalized_against_the_payload_scale() -> None:
    guidance = json.loads(FIXTURES.read_text(encoding="utf-8"))["guidance_range"]
    millions = {**guidance, "low": "120", "high": "125", "scale": 6}
    billions = {
        **guidance,
        "raw_value": "$0.12 billion to $0.125 billion",
        "low": "0.12",
        "high": "0.125",
        "scale": 9,
    }
    assert value_fingerprint(millions) == value_fingerprint(billions)
    assert value_fingerprint(millions) != value_fingerprint({**millions, "high": "130"})


def test_genuine_value_disagreement_is_still_detected() -> None:
    left = _arr(value="100", raw_value="$100 million")
    right = _arr(value="200", raw_value="$200 million")
    assert value_fingerprint(left) != value_fingerprint(right)

    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000004",
        payloads=[left, right],
    )
    assert [c.reason_codes for c in result.conflicts] == [["value_disagreement"]]
    # A disagreement across scales is still a disagreement: 1.2bn vs 1.2m.
    assert value_fingerprint(_arr(value="1.2", scale=9)) != value_fingerprint(
        _arr(value="1.2", scale=6)
    )


# --- fact identity must not collapse facts that differ on any axis -----------


def test_segment_disaggregated_facts_are_not_duplicates() -> None:
    """EMEA ARR and APAC ARR are two facts, whatever their values."""
    emea = _arr(dimensions={"segment": "EMEA"})
    apac = _arr(dimensions={"segment": "APAC"})
    assert duplicate_groups([emea, apac]) == []
    assert conflict_key_for(emea) != conflict_key_for(apac)

    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000005",
        payloads=[emea, apac],
    )
    assert result.conflicts == []
    assert not any("duplicate_candidate" in _blockers(p) for p in result.proposals)
    # ...and the ontology-keyed conflict path agrees: an EMEA and an APAC figure
    # share every comparability qualifier and are still not one figure.
    keys = {
        conflict_key_for(p.payload, ontology_comparability_key=str(p.comparability_key.get("key")))
        for p in result.proposals
    }
    assert len(keys) == 2


def test_same_number_in_two_currencies_is_not_a_duplicate() -> None:
    """Regression guard: currency scoping was already correct and must stay so."""
    usd = _arr()
    eur = _arr(
        unit="EUR",
        currency="EUR",
        qualifiers={
            "currency": "EUR",
            "construction": "reported_arr",
            "scope": "consolidated",
        },
    )
    assert duplicate_groups([usd, eur]) == []
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000006",
        payloads=[usd, eur],
    )
    assert result.conflicts == []
    assert not any("duplicate_candidate" in _blockers(p) for p in result.proposals)


def test_identity_separates_entities_qualifiers_and_units() -> None:
    """Each remaining identity axis alone makes two rows different facts."""
    base = _arr()
    assert duplicate_groups([base, _arr(entity_id=_OTHER_ENTITY)]) == []
    assert (
        duplicate_groups(
            [
                base,
                _arr(
                    qualifiers={
                        "currency": "USD",
                        "construction": "constant_currency_arr",
                        "scope": "consolidated",
                    }
                ),
            ]
        )
        == []
    )
    assert duplicate_groups([base, _arr(unit="percent")]) == []
    assert duplicate_groups([base, _arr()]) == [[0, 1]]


def test_duplicate_and_conflict_grouping_share_one_identity() -> None:
    """There is exactly one fact-identity implementation, and both paths use it."""
    import fel_workers.extraction.validate.duplicates as duplicates

    assert not hasattr(duplicates, "find_duplicates")
    emea = _arr(dimensions={"segment": "EMEA"})
    apac = _arr(dimensions={"segment": "APAC"})
    assert comparability_key_for(emea) != comparability_key_for(apac)
    assert conflict_key_for(emea) != conflict_key_for(apac)
    assert duplicate_groups([emea, apac]) == []
