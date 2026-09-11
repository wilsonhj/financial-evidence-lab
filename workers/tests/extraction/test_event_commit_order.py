"""Real-store event replay must not skip a lower ID that commits later (#135)."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from typing import Any

import psycopg
import pytest

from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.persist import (
    PostgresCheckpointStore,
    PostgresEventStore,
    PostgresPersistStore,
)
from fel_workers.extraction.types import ExtractionRunRequest, StageRecord

from .test_postgres_crash_resume import (
    _request,
    _seed_parents,
    _seed_run,
    ensure_extraction_database,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(url)


def _seed(conn: psycopg.Connection[Any]) -> ExtractionRunRequest:
    request = _request(str(uuid.uuid4()))
    _seed_parents(conn)
    _seed_run(conn, request)
    PostgresPersistStore(conn).mark_running(run_id=request.run_id, org_id=request.org_id)
    return request


def _append(conn: psycopg.Connection[Any], request: ExtractionRunRequest) -> None:
    PostgresEventStore(conn).append(
        org_id=request.org_id,
        run_id=request.run_id,
        event_type="run_started",
        payload={"workflow_version": request.workflow_version},
    )


def _rows(conn: psycopg.Connection[Any], run_id: str, after: int = 0) -> list[tuple[int, str]]:
    return conn.execute(
        "SELECT id, event_type FROM extraction_run_events"
        " WHERE run_id = %s AND id > %s ORDER BY id LIMIT 200",
        (run_id, after),
    ).fetchall()


def _blocked(conn: psycopg.Connection[Any], pid: int, blocker: int, future: Future[Any]) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if future.done():
            future.result()  # Surface writer errors instead of mistaking them for progress.
            return False
        if blocker in conn.execute("SELECT pg_blocking_pids(%s)", (pid,)).fetchone()[0]:
            return True
        Event().wait(0.01)
    raise AssertionError("writer neither completed nor reached the expected PostgreSQL lock")


def test_checkpoint_commit_order_preserves_resumed_events(extraction_db_url: str) -> None:
    inserted, release = Event(), Event()

    class PausedEvents(PostgresEventStore):
        def append(self, **kwargs: Any) -> Any:
            event = super().append(**kwargs)
            inserted.set()
            assert release.wait(10), "checkpoint pause timed out"
            return event

    with (
        psycopg.connect(extraction_db_url, autocommit=True) as first,
        psycopg.connect(extraction_db_url, autocommit=True) as second,
        psycopg.connect(extraction_db_url, autocommit=True) as reader,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        request = _seed(reader)
        output = {"valid": True}
        record = StageRecord(
            step_name="validate_request",
            attempt=1,
            status="succeeded",
            input_hash=hash_json({"run_id": request.run_id}),
            output_hash=hash_json(output),
            output=output,
        )
        pending = pool.submit(
            PostgresCheckpointStore(first).commit_succeeded_atomic,
            run_id=request.run_id,
            org_id=request.org_id,
            workflow_version=request.workflow_version,
            record=record,
            events=PausedEvents(first),
            event_payload={"step_name": record.step_name},
        )
        try:
            assert inserted.wait(5), "checkpoint never reached its real event INSERT"
            competing = pool.submit(_append, second, request)
            blocked = _blocked(reader, second.info.backend_pid, first.info.backend_pid, competing)
            visible = _rows(reader, request.run_id)
        finally:
            release.set()
        pending.result(timeout=5)
        competing.result(timeout=5)
        all_events = _rows(reader, request.run_id)
        resumed = _rows(reader, request.run_id, visible[-1][0] if visible else 0)
        assert visible + resumed == all_events, "replay skipped a later-committing lower event ID"
        assert blocked, "competing writer allocated its ID before the checkpoint committed"
        assert [kind for _, kind in all_events] == ["step_completed", "run_started"]
