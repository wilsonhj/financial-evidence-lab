"""Two real API transactions serialize before checking the same proposal version."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import psycopg
import pytest

from app.extraction import review
from tests.extraction.test_review_atomicity import command


@pytest.mark.parametrize("same_key", [False, True])
def test_two_current_reviews_commit_once(
    extraction_client,
    extraction_tenant,
    extraction_url,
    waiting_review_fixture,
    monkeypatch,
    same_key,
):
    fixture = waiting_review_fixture
    locked, release = Event(), Event()
    once = Lock()
    original = review._locked_rows

    def pause_first(*args):
        rows = original(*args)
        if once.acquire(blocking=False):
            locked.set()
            assert release.wait(5)
        return rows

    monkeypatch.setattr(review, "_locked_rows", pause_first)
    first_key = str(uuid.uuid4())
    second_key = first_key if same_key else str(uuid.uuid4())

    def submit(key):
        return extraction_client.post(
            "/v1/extractions/review",
            json=command(fixture["proposal"]),
            headers={**extraction_tenant["headers"], "Idempotency-Key": key},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, first_key)
        assert locked.wait(5)
        second = pool.submit(submit, second_key)
        observed = False
        try:
            with psycopg.connect(extraction_url, autocommit=True) as conn:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    observed = conn.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid))>0)"
                    ).fetchone()[0]
                    if observed:
                        break
                    time.sleep(0.01)
        finally:
            release.set()
        a, b = first.result(5), second.result(5)
    assert observed, "Second current writer was never observed blocked"
    assert a.status_code == 200, a.text
    assert b.status_code == (200 if same_key else 412), b.text
    if same_key:
        assert a.content == b.content
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM extraction_reviews WHERE org_id=%s",
                (extraction_tenant["org"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM approved_extraction_versions WHERE org_id=%s",
                (extraction_tenant["org"],),
            ).fetchone()[0]
            == 1
        )
