"""The bounded peer selection retains actual cross-payload accounting checks."""

from uuid import uuid4

import pytest

from tests.extraction.test_peer_boundary import clone
from tests.extraction.test_review_atomicity import command


@pytest.mark.parametrize("crpo,expected", [("300", 200), ("900", 422)])
def test_unselected_crpo_still_constrains_rpo(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, crpo, expected
):
    fixture = waiting_review_fixture
    common = {
        **fixture["payload"],
        "scale": 0,
        "dimensions": {"horizon": "12m"},
        "definition": None,
    }
    selected = clone(
        extraction_url,
        fixture,
        {
            **common,
            "metric_id": "rpo",
            "value": "500",
            "raw_value": "500",
            "qualifiers": {"currency": "USD", "usage_exemption": "none", "label_family": "rpo"},
        },
    )
    clone(
        extraction_url,
        fixture,
        {
            **common,
            "metric_id": "crpo",
            "value": crpo,
            "raw_value": crpo,
            "qualifiers": {"currency": "USD", "horizon_months": "12"},
        },
    )
    result = extraction_client.post(
        "/v1/extractions/review",
        json=command(selected["proposal"]),
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == expected, result.text


@pytest.mark.parametrize("profit,broken", [("70", False), ("90", True)])
def test_unselected_revenue_and_cogs_still_constrain_gross_profit(
    extraction_client,
    extraction_tenant,
    extraction_url,
    waiting_review_fixture,
    monkeypatch,
    profit,
    broken,
):
    from app.extraction import validation

    original = validation.evaluate
    evaluated = []

    def capture(*args):
        result = original(*args)
        evaluated.append(result)
        return result

    monkeypatch.setattr(validation, "evaluate", capture)
    fixture = waiting_review_fixture
    ids = {}
    for metric, value in [("revenue", "100"), ("cogs", "30"), ("gross_profit", profit)]:
        row = clone(
            extraction_url,
            fixture,
            {
                **fixture["payload"],
                "metric_id": metric,
                "value": value,
                "raw_value": value,
                "scale": 0,
                "definition": None,
                "qualifiers": {},
            },
        )
        ids[metric] = row["proposal"]
    result = extraction_client.post(
        "/v1/extractions/review",
        json=command(ids["gross_profit"]),
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    # These free-text metrics currently lack ontology comparability keys, so
    # neither reading can be approved. The existing arithmetic must still run.
    assert result.status_code == 422, result.text
    assert set(evaluated[0].drafts) == set(ids.values())
    blockers = evaluated[0].drafts[ids["gross_profit"]].validation_summary["blockers"]
    assert any(code.startswith("comparability_key unavailable:") for code in blockers)
    assert ("accounting_identity_violation:gross_profit_mismatch" in blockers) is broken


@pytest.mark.parametrize("segment,expected", [("60", 200), ("90", 422)])
def test_unselected_segments_still_constrain_total(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, segment, expected
):
    fixture = waiting_review_fixture
    for name, value in [("EMEA", "40"), ("APAC", segment)]:
        clone(
            extraction_url,
            fixture,
            {
                **fixture["payload"],
                "dimensions": {"region": name},
                "value": value,
                "raw_value": value,
            },
        )
    result = extraction_client.post(
        "/v1/extractions/review",
        json=command(fixture["proposal"]),
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == expected, result.text
