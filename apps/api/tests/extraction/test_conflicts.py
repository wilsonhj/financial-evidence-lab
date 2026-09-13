"""Explicit conflict adjudication retains every unselected proposal disposition."""

import uuid

import psycopg
from psycopg.types.json import Jsonb

from fel_workers.extraction.hashing import hash_json
from tests.extraction.test_review_atomicity import command


def alternative(url, tenant, fixture, value="110"):
    proposal, group = str(uuid.uuid4()), str(uuid.uuid4())
    payload = {**fixture["payload"], "value": value, "raw_value": "$" + value + " million"}
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO extraction_proposals(id,org_id,workspace_id,run_id,kind,metric_id,"
            "payload,raw_payload_hash,definition_hash,comparability_key,validation_summary,state) "
            "SELECT %s,org_id,workspace_id,run_id,kind,metric_id,%s,%s,definition_hash,"
            "comparability_key,"
            "validation_summary,'needs_review' FROM extraction_proposals WHERE id=%s",
            (proposal, Jsonb(payload), hash_json(payload), fixture["proposal"]),
        )
        conn.execute(
            "INSERT INTO extraction_proposal_evidence(proposal_id,org_id,source_span_id,"
            "document_version_id,role,citation_status) SELECT %s,org_id,source_span_id,"
            "document_version_id,"
            "role,citation_status FROM extraction_proposal_evidence WHERE proposal_id=%s",
            (proposal, fixture["proposal"]),
        )
        conn.execute(
            "INSERT INTO extraction_conflicts(id,org_id,workspace_id,conflict_key,reason_codes,"
            "occurrence_run_id) "
            "VALUES (%s,%s,%s,%s,ARRAY['value_disagreement'],%s)",
            (
                group,
                tenant["org"],
                tenant["workspace"],
                hash_json({"fixture": group}),
                fixture["run"],
            ),
        )
        for member in (proposal, fixture["proposal"]):
            conn.execute(
                "INSERT INTO extraction_conflict_members(conflict_id,org_id,proposal_id) "
                "VALUES (%s,%s,%s)",
                (group, tenant["org"], member),
            )
    return proposal, group


def decision(client, tenant, group, winners):
    detail = client.get("/v1/extraction-conflicts/" + group, headers=tenant["headers"])
    assert detail.status_code == 200, detail.text
    return {
        "conflict_id": group,
        "expected_etag": detail.json()["etag"],
        "member_versions": detail.json()["member_versions"],
        "selected_winner_ids": winners,
        "reason": "Selected supported occurrence.",
    }


def test_winner_retains_unselected_and_blocks_later_contradictory_acceptance(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    fixture, tenant = waiting_review_fixture, extraction_tenant
    other, group = alternative(extraction_url, tenant, fixture)
    body = {
        **command(fixture["proposal"]),
        "conflict_resolution": [decision(extraction_client, tenant, group, [fixture["proposal"]])],
    }
    result = extraction_client.post(
        "/v1/extractions/review",
        json=body,
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert result.status_code == 200, result.text
    with psycopg.connect(extraction_url) as conn:
        assert conn.execute(
            "SELECT state,version FROM extraction_proposals WHERE id=%s", (other,)
        ).fetchone() == ("needs_review", 1)
        assert (
            conn.execute(
                "SELECT status FROM extraction_runs WHERE id=%s", (fixture["run"],)
            ).fetchone()[0]
            == "waiting_review"
        )
    resolved = extraction_client.get(
        "/v1/extraction-conflicts/" + group, headers=tenant["headers"]
    ).json()
    assert resolved["resolution"]["selected_winner_ids"] == [fixture["proposal"]]
    later = extraction_client.post(
        "/v1/extractions/review",
        json=command(other),
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert later.status_code == 409, later.text


def test_stale_group_rolls_back_winner(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    fixture, tenant = waiting_review_fixture, extraction_tenant
    other, group = alternative(extraction_url, tenant, fixture)
    chosen = decision(extraction_client, tenant, group, [fixture["proposal"]])
    with psycopg.connect(extraction_url) as conn:
        conn.execute("UPDATE extraction_proposals SET version=version+1 WHERE id=%s", (other,))
    result = extraction_client.post(
        "/v1/extractions/review",
        json={**command(fixture["proposal"]), "conflict_resolution": [chosen]},
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert result.status_code == 412, result.text
