"""Malformed command representations are rejected before any durable mutation."""

import json
from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from tests.extraction.test_conflicts import alternative, decision
from tests.extraction.test_review_atomicity import command


def snapshot(url, org):
    tables = (
        "extraction_runs",
        "extraction_proposals",
        "extraction_reviews",
        "extraction_conflicts",
        "extraction_conflict_members",
        "extraction_run_events",
        "approved_extraction_records",
        "approved_extraction_versions",
        "audit_events",
        "idempotency_keys",
        "jobs",
    )
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(
                sql.SQL(
                    "SELECT to_jsonb(t) FROM {} t WHERE org_id=%s ORDER BY to_jsonb(t)::text"
                ).format(sql.Identifier(table)),
                (org,),
            ).fetchall()
            for table in tables
        }


def edit_body(fixture, source):
    payload = deepcopy(fixture["payload"])
    payload.pop("evidence", None)
    return {
        **command(fixture["proposal"], "edit"),
        "patch": [
            {
                "extraction_id": fixture["proposal"],
                "payload": payload,
                "evidence": [
                    {
                        "source_span_id": source["span"],
                        "document_version_id": source["version"],
                        "role": "supports",
                        "citation_status": "partial",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("numeric", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nonfinite_json_rejected_without_any_writes(
    extraction_client,
    extraction_tenant,
    extraction_url,
    waiting_review_fixture,
    source_fixture,
    numeric,
):
    body = edit_body(waiting_review_fixture, source_fixture)
    body["patch"][0]["payload"]["qualifiers"]["unrepresentable"] = "MARK"
    before = snapshot(extraction_url, extraction_tenant["org"])
    result = extraction_client.post(
        "/v1/extractions/review",
        content=json.dumps(body).replace('"MARK"', numeric),
        headers={
            **extraction_tenant["headers"],
            "Idempotency-Key": str(uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert result.status_code == 422, result.text
    assert snapshot(extraction_url, extraction_tenant["org"]) == before


@pytest.mark.parametrize("field", ["expected_versions", "member_versions"])
def test_uuid_map_collision_rejected_without_any_writes(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, field
):
    fixture = waiting_review_fixture
    proposal = fixture["proposal"]
    body = command(proposal)
    if field == "expected_versions":
        body[field] = {proposal: 2, proposal.upper(): 1}
    else:
        _, group = alternative(extraction_url, extraction_tenant, fixture)
        chosen = decision(extraction_client, extraction_tenant, group, [proposal])
        chosen[field][proposal] = 2
        chosen[field][proposal.upper()] = 1
        body["conflict_resolution"] = [chosen]
    before = snapshot(extraction_url, extraction_tenant["org"])
    result = extraction_client.post(
        "/v1/extractions/review",
        json=body,
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == 422, result.text
    assert snapshot(extraction_url, extraction_tenant["org"]) == before


def test_finite_nested_json_and_numeric_strings_are_preserved(
    extraction_client, extraction_tenant, waiting_review_fixture, source_fixture
):
    body = edit_body(waiting_review_fixture, source_fixture)
    preserved = {
        "number": 1.25,
        "integer": 9007199254740993,
        "decimal_string": "1e400",
        "literal_string": "NaN",
        "nested": [0, False, None, -2.5],
    }
    body["patch"][0]["payload"]["qualifiers"]["preserved"] = preserved
    result = extraction_client.post(
        "/v1/extractions/review",
        json=body,
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == 200, result.text
    record = extraction_client.get(
        "/v1/approved-extractions/" + result.json()["approved_record_ids"][0],
        headers=extraction_tenant["headers"],
    ).json()
    assert record["payload"]["qualifiers"]["preserved"] == preserved
    assert record["payload"]["value"] == body["patch"][0]["payload"]["value"]
