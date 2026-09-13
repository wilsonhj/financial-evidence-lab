"""Unselected unrelated drafts do not veto an otherwise valid approval."""

from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fel_workers.extraction.hashing import hash_json
from tests.extraction.test_conflicts import alternative, decision
from tests.extraction.test_review_atomicity import command


def clone(url, fixture, payload, *, evidence=True):
    proposal = str(uuid4())
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO extraction_proposals(id,org_id,workspace_id,run_id,kind,metric_id,"
            "payload,raw_payload_hash,definition_hash,comparability_key,validation_summary,state) "
            "SELECT %s,org_id,workspace_id,run_id,kind,%s,%s,%s,definition_hash,"
            "comparability_key,validation_summary,'needs_review' "
            "FROM extraction_proposals WHERE id=%s",
            (
                proposal,
                payload["metric_id"],
                Jsonb(payload),
                hash_json(payload),
                fixture["proposal"],
            ),
        )
        if evidence:
            conn.execute(
                "INSERT INTO extraction_proposal_evidence(proposal_id,org_id,source_span_id,"
                "document_version_id,role,citation_status) SELECT %s,org_id,source_span_id,"
                "document_version_id,role,citation_status FROM extraction_proposal_evidence "
                "WHERE proposal_id=%s",
                (proposal, fixture["proposal"]),
            )
    return {**fixture, "proposal": proposal, "payload": payload}


@pytest.mark.parametrize("damage", ["dimensions", "evidence"])
@pytest.mark.parametrize("related", [False, True])
def test_malformed_peer_only_blocks_when_potentially_related(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, damage, related
):
    fixture = waiting_review_fixture
    payload = deepcopy(fixture["payload"])
    if not related:
        payload["metric_id"] = "rpo"
    if damage == "dimensions":
        payload["dimensions"] = ["malformed source dimension"]
    peer = clone(extraction_url, fixture, payload, evidence=damage != "evidence")
    response = extraction_client.post(
        "/v1/extractions/review",
        json=command(fixture["proposal"]),
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == (422 if related else 200), response.text
    with psycopg.connect(extraction_url) as conn:
        assert conn.execute(
            "SELECT state,version,payload FROM extraction_proposals WHERE id=%s",
            (peer["proposal"],),
        ).fetchone() == ("needs_review", 1, payload)


def test_each_adjudication_records_only_its_winners_approvals(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    first = waiting_review_fixture
    payload = deepcopy(first["payload"])
    payload["period"] = {**payload["period"], "instant": "2025-09-30"}
    second = clone(extraction_url, first, payload)
    _, group1 = alternative(extraction_url, extraction_tenant, first)
    _, group2 = alternative(extraction_url, extraction_tenant, second)
    ids = [first["proposal"], second["proposal"]]
    body = {
        **command(ids[0]),
        "extraction_ids": ids,
        "expected_versions": dict.fromkeys(ids, 1),
        "conflict_resolution": [
            decision(extraction_client, extraction_tenant, group1, [ids[0]]),
            decision(extraction_client, extraction_tenant, group2, [ids[1]]),
        ],
    }
    response = extraction_client.post(
        "/v1/extractions/review",
        json=body,
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    with psycopg.connect(extraction_url) as conn:
        for group, winner in [(group1, ids[0]), (group2, ids[1])]:
            record = str(
                conn.execute(
                    "SELECT record_id FROM approved_extraction_versions WHERE origin_proposal_id=%s",
                    (winner,),
                ).fetchone()[0]
            )
            detail = extraction_client.get(
                "/v1/extraction-conflicts/" + group, headers=extraction_tenant["headers"]
            ).json()
            assert detail["resolution"]["approved_record_ids"] == [record]
