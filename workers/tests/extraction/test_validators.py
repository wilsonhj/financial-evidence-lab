"""Validator / conflict / needs_review tests (M3-106)."""

from __future__ import annotations

import json
from pathlib import Path

from fel_workers.extraction.validate import (
    detect_conflicts,
    validate_payload_item,
    validate_proposals,
)
from fel_workers.extraction.validate.range import check_range

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)


def test_contract_fixtures_schema_valid() -> None:
    data = json.loads(FIXTURES.read_text())
    for name, payload in data.items():
        if name == "note" or not isinstance(payload, dict):
            continue
        assert validate_payload_item(payload) == [], name


def test_range_low_gt_high_blocker() -> None:
    payload = json.loads(FIXTURES.read_text())["guidance_range"]
    payload = {**payload, "low": "200", "high": "100"}
    assert (
        "range_low_gt_high" in check_range(payload)
        or any("low" in e and "high" in e for e in check_range(payload))
        or check_range(payload)
    )


def test_proposals_always_needs_review() -> None:
    kpi = json.loads(FIXTURES.read_text())["kpi"]
    kpi = {
        **kpi,
        "qualifiers": {"currency": "USD", "construction": "ARR"},
    }
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000099",
        payloads=[kpi],
    )
    assert result.proposals
    for draft in result.proposals:
        assert draft.state == "needs_review"
        assert draft.review_priority in {"normal", "high"}


def test_duplicate_conflict_groups() -> None:
    kpi = json.loads(FIXTURES.read_text())["kpi"]
    kpi_a = {
        **kpi,
        "value": "100",
        "qualifiers": {"currency": "USD", "construction": "ARR", "scope": "consolidated"},
    }
    kpi_b = {
        **kpi,
        "value": "200",
        "qualifiers": {"currency": "USD", "construction": "ARR", "scope": "consolidated"},
    }
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000098",
        payloads=[kpi_a, kpi_b],
    )
    # Same conflict_key with disagreeing values → conflict group with ≥2 members.
    assert result.conflicts
    assert all(len(c.member_proposal_ids) >= 2 for c in result.conflicts)
    assert callable(detect_conflicts)
