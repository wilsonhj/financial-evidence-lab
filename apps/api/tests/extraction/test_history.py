"""Complete bounded histories omit internal checkpoint and worker data."""

import json
import uuid

import psycopg

from tests.extraction.test_proposal_reads import _insert, _payload


def test_proposal_pages_bind_state_and_preserve_empty_pages(
    extraction_client, extraction_tenant, extraction_url, seeded_runs
):
    tenant = extraction_tenant
    ids = [
        _insert(extraction_url, tenant, seeded_runs[0], _payload(tenant["entity"]))
        for _ in range(3)
    ]
    path = f"/v1/workspaces/{tenant['workspace']}/extractions"
    first = extraction_client.get(
        path, params={"limit": 2, "state": "proposed"}, headers=tenant["headers"]
    )
    assert first.status_code == 200, first.text
    page = first.json()
    cursor = page["next_cursor"]
    assert cursor
    second = extraction_client.get(
        path, params={"cursor": cursor, "state": "proposed"}, headers=tenant["headers"]
    )
    assert len(second.json()["items"]) == 1
    assert {item["id"] for item in page["items"] + second.json()["items"]} == set(ids)
    swapped = extraction_client.get(
        path, params={"cursor": cursor, "state": "rejected"}, headers=tenant["headers"]
    )
    assert swapped.status_code == 422
    empty = extraction_client.get(path, params={"state": "rejected"}, headers=tenant["headers"])
    assert empty.json() == {"items": [], "limit": 50, "next_cursor": None, "previous_cursor": None}


def test_steps_omit_real_checkpoint_output(
    extraction_client, extraction_tenant, extraction_url, seeded_runs
):
    tenant = extraction_tenant
    step = str(uuid.uuid4())
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO extraction_run_steps(id,org_id,run_id,step_name,attempt,status,input_hash,"
            "output_hash,workflow_version,schema_version,prompt_version,output,started_at) "
            "VALUES (%s,%s,%s,'assemble_evidence',1,'succeeded',%s,%s,'extraction-workflow/v3',"
            "'stage/v1','prompt/v1',%s,'2026-01-01Z')",
            (
                step,
                tenant["org"],
                seeded_runs[0],
                "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
                json.dumps({"source_text": "private checkpoint source text"}),
            ),
        )
    response = extraction_client.get(
        f"/v1/extraction-runs/{seeded_runs[0]}/steps", headers=tenant["headers"]
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["id"] == step and item["status"] == "succeeded"
    assert item["started_at"].startswith("2026-01-01")
    assert "source_text" not in response.text and "private checkpoint" not in response.text
    assert "output" not in item and "provider_response_id" not in item


def test_conflict_detail_has_complete_membership_and_etag(
    extraction_client, extraction_tenant, extraction_url, seeded_runs
):
    tenant = extraction_tenant
    members = [
        _insert(extraction_url, tenant, seeded_runs[0], _payload(tenant["entity"]))
        for _ in range(2)
    ]
    group = str(uuid.uuid4())
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO extraction_conflicts(id,org_id,workspace_id,conflict_key,reason_codes) "
            "VALUES (%s,%s,%s,%s,ARRAY['value_disagreement'])",
            (group, tenant["org"], tenant["workspace"], "sha256:" + "f" * 64),
        )
        for member in members:
            conn.execute(
                "INSERT INTO extraction_conflict_members(conflict_id,proposal_id,org_id) "
                "VALUES (%s,%s,%s)",
                (group, member, tenant["org"]),
            )
    response = extraction_client.get(f"/v1/extraction-conflicts/{group}", headers=tenant["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["member_versions"] == dict.fromkeys(members, 1)
    assert response.json()["etag"] == response.headers["ETag"]
    assert response.json()["resolution"] is None and response.json()["occurrence_run_id"] is None
    listed = extraction_client.get(
        f"/v1/workspaces/{tenant['workspace']}/extraction-conflicts", headers=tenant["headers"]
    )
    assert listed.json()["items"] == [response.json()]
