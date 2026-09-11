"""Real-store event replay must not skip a lower ID that commits later (#135)."""

from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
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
from fel_workers.extraction.types import ConflictDraft, ExtractionRunRequest, StageRecord

from .test_persist_atomicity import _counts, _drafts, _member_ids
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


def _connect(url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(url, autocommit=True, options="-c statement_timeout=5000")


def _append(conn: psycopg.Connection[Any], request: ExtractionRunRequest) -> None:
    PostgresEventStore(conn).append(
        org_id=request.org_id,
        run_id=request.run_id,
        event_type="run_started",
        payload={"workflow_version": request.workflow_version},
    )


def _commit(
    conn: psycopg.Connection[Any],
    request: ExtractionRunRequest,
    kind: str,
    events: PostgresEventStore,
    checkpoint: PostgresCheckpointStore | None = None,
    persist: PostgresPersistStore | None = None,
) -> None:
    if kind == "proposals":
        drafts = _drafts()
        (persist or PostgresPersistStore(conn)).persist_outputs_atomic(
            run_id=request.run_id,
            org_id=request.org_id,
            workspace_id=request.workspace_id,
            proposals=drafts,
            conflicts=[
                ConflictDraft(
                    conflict_key=f"event-order|{request.run_id}",
                    reason_codes=["value_disagreement"],
                    member_proposal_ids=_member_ids(request.run_id, drafts),
                )
            ],
            events=events,
        )
        return
    output = {"valid": True}
    (checkpoint or PostgresCheckpointStore(conn)).commit_succeeded_atomic(
        run_id=request.run_id,
        org_id=request.org_id,
        workflow_version=request.workflow_version,
        record=StageRecord(
            step_name="validate_request",
            attempt=1,
            status="succeeded",
            input_hash=hash_json({"run_id": request.run_id}),
            output_hash=hash_json(output),
            output=output,
        ),
        events=events,
        event_payload={"step_name": "validate_request"},
    )


def _api_append(conn: psycopg.Connection[Any], request: ExtractionRunRequest) -> None:
    # The planned API takes run locks before children and appends in that same
    # transaction. Exercise that interaction with the actual least-privilege role.
    conn.execute("SET ROLE fel_app")
    with conn.transaction():
        conn.execute(
            "SELECT set_config('request.jwt.claims', %s, true)",
            (json.dumps({"org_id": request.org_id}),),
        )
        conn.execute(
            "SELECT id FROM extraction_runs WHERE id=%s AND org_id=%s FOR UPDATE",
            (request.run_id, request.org_id),
        )
        _append(conn, request)
        conn.execute(
            "UPDATE extraction_runs SET cancel_requested_at=now() WHERE id=%s AND org_id=%s",
            (request.run_id, request.org_id),
        )


def _rows(conn: psycopg.Connection[Any], run_id: str, after: int = 0) -> list[tuple[int, str]]:
    return conn.execute(
        "SELECT id, event_type FROM extraction_run_events"
        " WHERE run_id = %s AND id > %s ORDER BY id LIMIT 200",
        (run_id, after),
    ).fetchall()


def _replay(conn: psycopg.Connection[Any], run_id: str, after: int) -> list[tuple[int, str]]:
    replayed = []
    while rows := conn.execute(
        "SELECT id, event_type FROM extraction_run_events"
        " WHERE run_id=%s AND id>%s ORDER BY id LIMIT 1",
        (run_id, after),
    ).fetchall():
        replayed.extend(rows)
        after = rows[-1][0]
    return replayed


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


@pytest.mark.parametrize("kind", ["checkpoint", "proposals"])
@pytest.mark.parametrize("rollback", [False, True], ids=["commit", "rollback"])
@pytest.mark.parametrize("api_writer", [False, True], ids=["worker", "api"])
def test_atomic_commit_order_preserves_resumed_events(
    extraction_db_url: str, kind: str, rollback: bool, api_writer: bool
) -> None:
    inserted, release = Event(), Event()

    class RollbackProbe(Exception):
        pass

    class PausedEvents(PostgresEventStore):
        def append(self, **kwargs: Any) -> Any:
            event = super().append(**kwargs)
            inserted.set()
            assert release.wait(10), "atomic event pause timed out"
            if rollback:
                raise RollbackProbe
            return event

    with (
        _connect(extraction_db_url) as first,
        _connect(extraction_db_url) as second,
        _connect(extraction_db_url) as reader,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        request = _seed(reader)
        first.execute("SET ROLE fel_worker")
        second.execute("SET ROLE fel_worker")
        pending = pool.submit(_commit, first, request, kind, PausedEvents(first))
        try:
            assert inserted.wait(5), "atomic writer never reached its real event INSERT"
            allocated = first.execute(
                "SELECT max(id) FROM extraction_run_events WHERE run_id=%s", (request.run_id,)
            ).fetchone()[0]
            competing = pool.submit(_api_append if api_writer else _append, second, request)
            blocked = _blocked(reader, second.info.backend_pid, first.info.backend_pid, competing)
            visible = _rows(reader, request.run_id)
        finally:
            release.set()
        if rollback:
            with pytest.raises(RollbackProbe):
                pending.result(timeout=5)
        else:
            pending.result(timeout=5)
        competing.result(timeout=5)
        all_events = _rows(reader, request.run_id)
        resumed = _replay(reader, request.run_id, visible[-1][0] if visible else 0)
        assert visible + resumed == all_events, "replay skipped a later-committing lower event ID"
        assert blocked, "competing writer allocated its ID before the atomic writer finished"
        expected = "step_completed" if kind == "checkpoint" else "proposals_persisted"
        assert [event_type for _, event_type in all_events] == (
            ["run_started"] if rollback else [expected, "run_started"]
        )
        assert all_events[-1][0] > allocated  # Rollbacks leave legal identity gaps.
        if kind == "proposals":
            assert _counts(reader, request.run_id) == dict.fromkeys(
                ("proposals", "evidence", "members"), 0 if rollback else 2
            )
        else:
            assert reader.execute(
                "SELECT count(*) FROM extraction_run_steps WHERE run_id=%s", (request.run_id,)
            ).fetchone()[0] == (0 if rollback else 1)
        if api_writer:
            assert (
                reader.execute(
                    "SELECT cancel_requested_at FROM extraction_runs WHERE id=%s", (request.run_id,)
                ).fetchone()[0]
                is not None
            )


@pytest.mark.parametrize("kind", ["checkpoint", "proposals"])
def test_atomic_writer_locks_before_entering_child_writes(
    extraction_db_url: str, kind: str
) -> None:
    entered_child = Event()

    class ObservedCheckpoint(PostgresCheckpointStore):
        def _insert_step_row(self, **kwargs: Any) -> None:
            entered_child.set()
            super()._insert_step_row(**kwargs)

    class ObservedPersist(PostgresPersistStore):
        def persist_proposals(self, **kwargs: Any) -> Any:
            entered_child.set()
            return super().persist_proposals(**kwargs)

    with (
        _connect(extraction_db_url) as first,
        _connect(extraction_db_url) as second,
        _connect(extraction_db_url) as reader,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        request = _seed(reader)
        second.execute("SET ROLE fel_worker")
        with first.transaction():
            # Existing SHARE is compatible with another child's SHARE. A writer
            # must wait BEFORE entering either child path, avoiding lock upgrades.
            first.execute("SELECT id FROM extraction_runs WHERE id=%s FOR SHARE", (request.run_id,))
            pending = pool.submit(
                _commit,
                second,
                request,
                kind,
                PostgresEventStore(second),
                ObservedCheckpoint(second),
                ObservedPersist(second),
            )
            assert _blocked(reader, second.info.backend_pid, first.info.backend_pid, pending)
            assert not entered_child.is_set(), "child writes began before exclusive run locking"
        pending.result(timeout=5)
        assert entered_child.is_set()


def test_standalone_waits_before_identity_allocation_and_other_runs_progress(
    extraction_db_url: str,
) -> None:
    with (
        _connect(extraction_db_url) as first,
        _connect(extraction_db_url) as second,
        _connect(extraction_db_url) as reader,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        request, other = _seed(reader), _seed(reader)
        second.execute("SET ROLE fel_worker")
        sequence_before = reader.execute(
            "SELECT last_value FROM extraction_run_events_id_seq"
        ).fetchone()
        with first.transaction():
            # The actual standalone append's nested savepoint has ended, but its
            # lock must remain attached to this surrounding transaction.
            _append(first, request)
            sequence_after_first = reader.execute(
                "SELECT last_value FROM extraction_run_events_id_seq"
            ).fetchone()
            pending = pool.submit(_append, second, request)
            assert _blocked(reader, second.info.backend_pid, first.info.backend_pid, pending)
            assert (
                reader.execute("SELECT last_value FROM extraction_run_events_id_seq").fetchone()
                == sequence_after_first
            )
            assert sequence_after_first[0] > sequence_before[0]
            _append(reader, other)
            assert len(_rows(reader, other.run_id)) == 1
            assert _rows(reader, request.run_id) == []
        pending.result(timeout=5)
        assert len(_replay(reader, request.run_id, 0)) == 2


@pytest.mark.parametrize("invalid", ["missing", "wrong_org", "terminal"])
def test_failed_append_keeps_original_guards_and_releases_transaction(
    extraction_db_url: str, invalid: str
) -> None:
    with _connect(extraction_db_url) as conn:
        request = _seed(conn)
        rejected = request
        if invalid == "missing":
            rejected = replace(request, run_id=str(uuid.uuid4()))
        elif invalid == "wrong_org":
            rejected = replace(request, org_id=str(uuid.uuid4()))
        else:
            PostgresPersistStore(conn).set_run_status(
                run_id=request.run_id, org_id=request.org_id, status="cancelled"
            )
        conn.execute("SET ROLE fel_worker")
        with pytest.raises(psycopg.errors.RaiseException, match="same-organization|terminal"):
            _append(conn, rejected)
        assert _rows(conn, request.run_id) == []
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
