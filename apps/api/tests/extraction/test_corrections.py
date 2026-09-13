"""Approved history appends immutable versions and replays the exact original correction."""

import uuid

import psycopg

from tests.extraction.test_review_atomicity import command


def test_corrections_preserve_history_and_exact_receipt(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    accepted = extraction_client.post(
        "/v1/extractions/review",
        json=command(fixture["proposal"]),
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 200, accepted.text
    record_id = accepted.json()["approved_record_ids"][0]
    path = "/v1/approved-extractions/" + record_id
    original = extraction_client.get(path, headers=tenant["headers"])
    assert original.status_code == 200, original.text
    body = {
        "reason": "Corrected source reading.",
        "payload": {**original.json()["payload"], "value": "101", "raw_value": "$101 million"},
        "evidence": original.json()["evidence"],
    }
    headers = {
        **tenant["headers"],
        "Idempotency-Key": str(uuid.uuid4()),
        "If-Match": original.headers["ETag"],
    }
    first = extraction_client.post(path + "/corrections", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["parent_version_id"] == original.json()["version_id"]
    second = extraction_client.post(
        path + "/corrections",
        json={**body, "payload": {**body["payload"], "value": "102"}},
        headers={
            **headers,
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": first.headers["ETag"],
        },
    )
    assert second.status_code == 201, second.text
    replay = extraction_client.post(path + "/corrections", json=body, headers=headers)
    assert replay.content == first.content and replay.headers["ETag"] == first.headers["ETag"]
    stale = extraction_client.post(
        path + "/corrections", json=body, headers={**headers, "Idempotency-Key": str(uuid.uuid4())}
    )
    assert stale.status_code == 412, stale.text
    history = extraction_client.get(path + "/versions?limit=2", headers=tenant["headers"])
    assert history.status_code == 200, history.text
    assert [item["version"] for item in history.json()["items"]] == [1, 2]
    later = extraction_client.get(
        path + "/versions",
        params={"cursor": history.json()["next_cursor"]},
        headers=tenant["headers"],
    )
    assert [item["version"] for item in later.json()["items"]] == [3]
    old = extraction_client.get(
        path + "/versions/" + original.json()["version_id"], headers=tenant["headers"]
    )
    assert old.json() == original.json()
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM extraction_reviews WHERE org_id=%s", (tenant["org"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM approved_extraction_versions WHERE org_id=%s",
                (tenant["org"],),
            ).fetchone()[0]
            == 3
        )
