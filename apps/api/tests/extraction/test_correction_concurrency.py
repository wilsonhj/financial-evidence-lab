"""Competing real corrections append once and preserve the immutable old head."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import psycopg
import pytest

from app.extraction import receipts, review
from tests.extraction.test_review_atomicity import command


@pytest.mark.parametrize("same_key", [False, True])
def test_same_head_corrections_serialize_and_replay(
    extraction_client,
    extraction_tenant,
    extraction_url,
    waiting_review_fixture,
    monkeypatch,
    same_key,
):
    tenant = extraction_tenant
    accepted = extraction_client.post(
        "/v1/extractions/review",
        json=command(waiting_review_fixture["proposal"]),
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 200, accepted.text
    record = accepted.json()["approved_record_ids"][0]
    path = "/v1/approved-extractions/" + record
    original = extraction_client.get(path, headers=tenant["headers"])
    assert original.status_code == 200, original.text
    body = {
        "reason": "Verified source again.",
        "payload": original.json()["payload"],
        "evidence": original.json()["evidence"],
    }
    locked, release, second_started = Event(), Event(), Event()
    once = Lock()
    original_rows, original_begin = review._locked_rows, receipts.begin
    pids = []

    def capture_connection(conn, *args):
        pids.append(conn.info.backend_pid)
        if len(pids) == 2:
            second_started.set()
        return original_begin(conn, *args)

    def pause_first(*args):
        rows = original_rows(*args)
        if once.acquire(blocking=False):
            locked.set()
            assert release.wait(10), "First correction was not released"
        return rows

    monkeypatch.setattr(receipts, "begin", capture_connection)
    monkeypatch.setattr(review, "_locked_rows", pause_first)
    first_key = str(uuid.uuid4())
    second_key = first_key if same_key else str(uuid.uuid4())

    def submit(key):
        return extraction_client.post(
            path + "/corrections",
            json=body,
            headers={
                **tenant["headers"],
                "Idempotency-Key": key,
                "If-Match": original.headers["ETag"],
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, first_key)
        try:
            assert locked.wait(5), "First correction never acquired its resource locks"
            second = pool.submit(submit, second_key)
            assert second_started.wait(5), "Second correction never entered its transaction"
            assert pids[0] != pids[1]
            observed = False
            with psycopg.connect(extraction_url, autocommit=True) as conn:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    observed = (
                        pids[0]
                        in conn.execute("SELECT pg_blocking_pids(%s)", (pids[1],)).fetchone()[0]
                    )
                    if observed:
                        break
                    time.sleep(0.01)
            assert observed, "Second correction was not blocked by the first writer"
        finally:
            release.set()
        a, b = first.result(5), second.result(5)
    assert a.status_code == 201, a.text
    assert b.status_code == (201 if same_key else 412), b.text
    if same_key:
        assert b.content == a.content
        assert b.headers["ETag"] == a.headers["ETag"]
        assert b.headers["Location"] == a.headers["Location"]
    current = extraction_client.get(path, headers=tenant["headers"])
    assert current.json() == a.json()
    assert current.json()["version"] == 2
    old = extraction_client.get(
        path + "/versions/" + original.json()["version_id"], headers=tenant["headers"]
    )
    assert old.content == original.content
    assert old.headers["ETag"] == original.headers["ETag"]
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM approved_extraction_versions WHERE record_id=%s", (record,)
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_events WHERE org_id=%s "
                "AND action='extraction.corrected'",
                (tenant["org"],),
            ).fetchone()[0]
            == 1
        )
        rows = conn.execute(
            "SELECT key FROM idempotency_keys WHERE org_id=%s " "AND endpoint='extraction.correct'",
            (tenant["org"],),
        ).fetchall()
        assert rows == [(first_key,)]
