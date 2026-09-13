"""Approval composes frozen financial rules over real pinned evidence bytes."""

from copy import deepcopy
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.db import tenant_connection
from tests.extraction.test_run_creation import _create


def _guidance(entity, low, high):
    return {
        "schema_version": "extraction-payload/v1",
        "kind": "guidance",
        "entity_id": entity,
        "issuer_label": "Fixture",
        "metric_id": "arr",
        "raw_value": f"{low} to {high}",
        "shape": "range",
        "low": low,
        "high": high,
        "unit": "USD",
        "currency": "USD",
        "scale": 0,
        "sign": "negative" if low.startswith("-") else "positive",
        "period": {"type": "forecast", "start": "2026-01-01", "end": "2026-12-31"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "management_assertion",
    }


@pytest.mark.parametrize(
    "low,high,blocked", [("20", "10", True), ("10", "-20", True), ("-10", "-20", False)]
)
def test_existing_range_rule_and_real_byte_pins(
    extraction_client, extraction_tenant, source_fixture, low, high, blocked
):
    from app.extraction import validation
    from app.extraction.runs import locked_run

    tenant = extraction_tenant
    run_id = _create(extraction_client, tenant, source_fixture).json()["id"]
    payload = _guidance(tenant["entity"], low, high)
    original = deepcopy(payload)
    ctx = TenantContext(org_id=tenant["org"], user_id=tenant["user"], role="owner")
    with tenant_connection(ctx) as conn:
        run = locked_run(conn, UUID(run_id), tenant["org"])
        result = validation.evaluate(
            conn,
            [
                {
                    "id": "source-row",
                    "run_id": run_id,
                    "payload": payload,
                    "evidence": [
                        {
                            "source_span_id": source_fixture["span"],
                            "document_version_id": source_fixture["version"],
                            "role": "supports",
                        }
                    ],
                }
            ],
            {run_id: run},
        )
    draft = result.drafts["source-row"]
    assert bool(draft.validation_summary["blockers"]) is blocked, draft.validation_summary
    assert payload == original
    if not blocked:
        assert (draft.payload["low"], draft.payload["high"]) == ("-20", "-10")
        assert draft.evidence[0]["citation_status"] == "verified"
        assert result.context["source_runs"][0]["policy_id"] == tenant["policy"]


def test_unknown_kind_cannot_disappear(extraction_client, extraction_tenant, source_fixture):
    from app.extraction import validation
    from app.extraction.runs import locked_run

    tenant = extraction_tenant
    run_id = _create(extraction_client, tenant, source_fixture).json()["id"]
    ctx = TenantContext(org_id=tenant["org"], user_id=tenant["user"], role="owner")
    with tenant_connection(ctx) as conn:
        run = locked_run(conn, UUID(run_id), tenant["org"])
        with pytest.raises(HTTPException) as failure:
            validation.evaluate(
                conn,
                [
                    {
                        "id": "source-row",
                        "run_id": run_id,
                        "payload": {"kind": "invented"},
                        "evidence": [],
                    }
                ],
                {run_id: run},
            )
        assert failure.value.status_code == 422


@pytest.mark.parametrize("damage", ["bytes", "claimed_hash", "carried_sign", "duplicate_identity"])
def test_revalidation_does_not_repair_evidence_or_lose_source_identity(
    extraction_client, extraction_tenant, source_fixture, damage
):
    from app.extraction import validation
    from app.extraction.runs import locked_run

    tenant = extraction_tenant
    run_id = _create(extraction_client, tenant, source_fixture).json()["id"]
    payload = _guidance(tenant["entity"], "-20", "-10")
    row = {
        "id": "first-row",
        "run_id": run_id,
        "payload": payload,
        "evidence": [
            {
                "source_span_id": source_fixture["span"],
                "document_version_id": source_fixture["version"],
                "role": "supports",
            }
        ],
    }
    if damage == "claimed_hash":
        payload["evidence"] = [{**row["evidence"][0], "text_hash": "sha256:" + "0" * 64}]
    if damage == "carried_sign":
        row["validation_summary"] = {
            "ok": False,
            "blockers": ["sign contradicts value: declared positive, value is negative"],
        }
    if damage == "bytes":
        source_fixture["path"].write_text("changed source")
    rows = [row]
    if damage == "duplicate_identity":
        rows.append({**deepcopy(row), "id": "second-row"})
    ctx = TenantContext(org_id=tenant["org"], user_id=tenant["user"], role="owner")
    with tenant_connection(ctx) as conn:
        run = locked_run(conn, UUID(run_id), tenant["org"])
        if damage in ("bytes", "claimed_hash"):
            with pytest.raises(HTTPException) as failure:
                validation.evaluate(conn, rows, {run_id: run})
            assert failure.value.status_code == 422
        else:
            result = validation.evaluate(conn, rows, {run_id: run})
            assert result.drafts["first-row"].validation_summary["blockers"]
            if damage == "duplicate_identity":
                assert set(result.drafts) == {"first-row", "second-row"}
                assert result.conflicts[0].member_proposal_ids == ["first-row", "second-row"]
