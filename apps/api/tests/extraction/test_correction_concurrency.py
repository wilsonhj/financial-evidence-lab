"""Same-head concurrent corrections serialize on the real run lock."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import psycopg
import pytest

from app.extraction import review
from tests.extraction.test_review_atomicity import command


def _approve(client, tenant, fixture):
    accepted = client.post(
        "/v1/extractions/review",
        json=command(fixture["proposal"]),
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 200, accepted.text
    record_id = accepted.json()["approved_record_ids"][0]
    original = client.get("/v1/approved-extractions/" + record_id, headers=tenant["headers"])
    assert original.status_code == 200, original.text
    return record_id, original


def _body(original, value):
    payload = {**original.json()["payload"], "value": value, "raw_value": f"${value} million"}
    return {
        "reason": "Corrected source reading.",
        "payload": payload,
        "evidence": original.json()["evidence"],
    }


def _submit(client, tenant, record_id, body, etag, key):
    return client.post(
        f"/v1/approved-extractions/{record_id}/corrections",
        json=body,
        headers={**tenant["headers"], "Idempotency-Key": key, "If-Match": etag},
    )


def _wait_blocked(url, timeout=3):
    deadline = time.monotonic() + timeout
    with psycopg.connect(url, autocommit=True) as conn:
        while time.monotonic() < deadline:
            blocked = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid))>0)"
            ).fetchone()[0]
            if blocked:
                return True
            time.sleep(0.01)
    return False


def _counts(url, org):
    with psycopg.connect(url) as conn:
        versions = conn.execute(
            "SELECT count(*) FROM approved_extraction_versions WHERE org_id=%s", (org,)
        ).fetchone()[0]
        audits = conn.execute(
            "SELECT count(*) FROM audit_events "
            "WHERE org_id=%s AND action='extraction.corrected'",
            (org,),
        ).fetchone()[0]
        receipts = conn.execute(
            "SELECT response_status FROM idempotency_keys "
            "WHERE org_id=%s AND endpoint='extraction.correct' ORDER BY key",
            (org,),
        ).fetchall()
    return versions, audits, [row[0] for row in receipts]


@pytest.mark.parametrize("same_key", [False, True])
def test_two_current_corrections_commit_once(
    extraction_client,
    extraction_tenant,
    extraction_url,
    waiting_review_fixture,
    monkeypatch,
    same_key,
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    record_id, original = _approve(extraction_client, tenant, fixture)
    etag = original.headers["ETag"]
    first_body = _body(original, "101")
    second_body = first_body if same_key else _body(original, "102")
    locked, release, once = Event(), Event(), Lock()
    pause = review._locked_rows

    def pause_first(*args):
        rows = pause(*args)
        if once.acquire(blocking=False):
            locked.set()
            assert release.wait(5)
        return rows

    monkeypatch.setattr(review, "_locked_rows", pause_first)
    first_key = str(uuid.uuid4())
    second_key = first_key if same_key else str(uuid.uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            _submit, extraction_client, tenant, record_id, first_body, etag, first_key
        )
        assert locked.wait(5), "First correction never reached the run lock"
        second = pool.submit(
            _submit, extraction_client, tenant, record_id, second_body, etag, second_key
        )
        try:
            blocked = _wait_blocked(extraction_url)
        finally:
            release.set()
        winner, waiter = first.result(5), second.result(5)

    assert blocked, "Second current correction was never observed blocked"
    assert winner.status_code == 201, winner.text
    if same_key:
        assert waiter.status_code == 201, waiter.text
        assert waiter.content == winner.content
        assert waiter.headers["ETag"] == winner.headers["ETag"]
        assert waiter.headers["Location"] == winner.headers["Location"]
        assert waiter.json()["payload"]["value"] == "101"
    else:
        assert waiter.status_code == 412, waiter.text
        assert waiter.json()["error"]["code"] == "PRECONDITION_FAILED"

    current = extraction_client.get(
        "/v1/approved-extractions/" + record_id, headers=tenant["headers"]
    )
    assert current.status_code == 200, current.text
    assert current.headers["ETag"] == winner.headers["ETag"]
    assert current.json()["version"] == original.json()["version"] + 1
    assert current.json()["parent_version_id"] == original.json()["version_id"]
    assert current.json()["payload"]["value"] == "101"
    previous = extraction_client.get(
        f"/v1/approved-extractions/{record_id}/versions/{original.json()['version_id']}",
        headers=tenant["headers"],
    )
    assert previous.json() == original.json()
    versions, audits, receipts = _counts(extraction_url, tenant["org"])
    assert versions == 2
    assert audits == 1
    assert receipts == [201]
