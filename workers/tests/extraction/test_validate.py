"""Validator + conflict grouping tests (M3-106)."""

from __future__ import annotations

import json
from pathlib import Path

from fel_ontology import load_saas_metrics
from fel_workers.extraction.validate import validate_payload_item, validate_proposals
from fel_workers.extraction.validate.checks import accounting_errors

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)


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
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    kpi = dict(data["kpi"])
    kpi["qualifiers"] = {
        "currency": "USD",
        "construction": "reported_arr",
        "scope": "consolidated",
    }
    result = validate_proposals(run_id="00000000-0000-4000-8000-000000000001", payloads=[kpi])
    assert result.proposals
    assert all(p.state == "needs_review" for p in result.proposals)


def test_conflict_groups_deterministic() -> None:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    left = dict(data["kpi"])
    right = dict(data["kpi"])
    left["qualifiers"] = right["qualifiers"] = {
        "currency": "USD",
        "construction": "reported_arr",
        "scope": "consolidated",
    }
    right["value"] = "200"
    right["raw_value"] = "$200 million"
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000002",
        payloads=[left, right],
    )
    assert len(result.conflicts) == 1
    assert len(result.conflicts[0].member_proposal_ids) == 2
