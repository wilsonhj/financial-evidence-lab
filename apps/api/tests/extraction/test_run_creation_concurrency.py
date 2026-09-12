"""Creation observes a coherent workspace cutoff while evidence is verified."""

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg

from tests.extraction.test_run_creation import _create


def test_workspace_cutoff_change_serializes_with_create(
    extraction_client, extraction_tenant, extraction_url, source_fixture, monkeypatch
):
    from app.extraction import evidence

    verified = threading.Event()
    release = threading.Event()
    pids = queue.Queue()
    original = evidence.verify_spans

    def paused_verify(conn, *args):
        result = original(conn, *args)
        pids.put(conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
        verified.set()
        assert release.wait(5)
        return result

    def lower_cutoff():
        with psycopg.connect(extraction_url) as conn:
            pids.put(conn.execute("SELECT pg_backend_pid()").fetchone()[0])
            conn.execute(
                "UPDATE workspaces SET as_of='2025-01-01Z' WHERE id=%s",
                (extraction_tenant["workspace"],),
            )

    monkeypatch.setattr(evidence, "verify_spans", paused_verify)
    with ThreadPoolExecutor(max_workers=2) as pool:
        created = pool.submit(_create, extraction_client, extraction_tenant, source_fixture)
        assert verified.wait(3)
        first_pid = pids.get(timeout=3)
        changed = pool.submit(lower_cutoff)
        second_pid = pids.get(timeout=3)
        try:
            with psycopg.connect(extraction_url, autocommit=True) as observer:
                deadline = time.monotonic() + 2
                blockers = []
                while time.monotonic() < deadline:
                    blockers = observer.execute(
                        "SELECT pg_blocking_pids(%s)", (second_pid,)
                    ).fetchone()[0]
                    if first_pid in blockers:
                        break
                    time.sleep(0.01)
                assert first_pid in blockers, "workspace cutoff changed during creation"
        finally:
            release.set()
        assert created.result(timeout=3).status_code == 202
        changed.result(timeout=3)
