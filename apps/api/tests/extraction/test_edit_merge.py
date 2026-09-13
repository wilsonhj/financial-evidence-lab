"""Full replacements and merge source selection leave immutable proposal bytes intact."""

import uuid

import psycopg

from tests.extraction.test_conflicts import alternative, decision
from tests.extraction.test_review_atomicity import command


def test_explicit_edit_preserves_original_payload(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    fixture, tenant = waiting_review_fixture, extraction_tenant
    payload = {key: value for key, value in fixture["payload"].items() if key != "evidence"}
    payload["value"] = "101"
    payload["raw_value"] = "$101 million"
    body = {
        **command(fixture["proposal"], "edit"),
        "patch": [
            {
                "extraction_id": fixture["proposal"],
                "payload": payload,
                "evidence": [
                    {
                        "source_span_id": source_fixture["span"],
                        "document_version_id": source_fixture["version"],
                        "role": "supports",
                        "citation_status": "invalid",
                    }
                ],
            }
        ],
    }
    result = extraction_client.post(
        "/v1/extractions/review",
        json=body,
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert result.status_code == 200, result.text
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute(
                "SELECT payload FROM extraction_proposals WHERE id=%s", (fixture["proposal"],)
            ).fetchone()[0]
            == fixture["payload"]
        )
        row = conn.execute(
            "SELECT payload,evidence_manifest FROM approved_extraction_versions WHERE org_id=%s",
            (tenant["org"],),
        ).fetchone()
        assert row[0]["value"] == "101" and row[1][0]["citation_status"] == "verified"


def test_merge_copies_selected_source_and_supersedes_inputs(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    fixture, tenant = waiting_review_fixture, extraction_tenant
    other, group = alternative(extraction_url, tenant, fixture)
    ids = [fixture["proposal"], other]
    body = {
        "action": "merge",
        "extraction_ids": ids,
        "expected_versions": dict.fromkeys(ids, 1),
        "reason": "Merge source evidence.",
        "patch": {"payload_source_id": fixture["proposal"]},
        "conflict_resolution": [decision(extraction_client, tenant, group, [fixture["proposal"]])],
    }
    result = extraction_client.post(
        "/v1/extractions/review",
        json=body,
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert result.status_code == 200, result.text
    assert set(result.json()["proposal_states"].values()) == {"superseded"}
    assert len(result.json()["approved_record_ids"]) == 1
    with psycopg.connect(extraction_url) as conn:
        row = conn.execute(
            "SELECT payload,evidence_manifest FROM approved_extraction_versions WHERE org_id=%s",
            (tenant["org"],),
        ).fetchone()
        assert row[0]["value"] == fixture["payload"]["value"] and len(row[1]) == 1
