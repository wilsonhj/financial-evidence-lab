"""Both persist stores refuse to mutate a terminal run (#146).

Frozen 0004's ``fel_guard_extraction_run`` raises ``terminal extraction run
cannot be mutated`` on ANY update to a run row already ``succeeded`` /
``failed`` / ``cancelled``. ``MemoryPersistStore`` had no such guard, which
is why #146 could only be reproduced against Postgres: every unit-level
consumer test happily re-ran a terminal run. The memory store must reject
exactly what the trigger rejects, with a typed error the consumer can act on,
and the Postgres store must raise that same typed error BEFORE the trigger
would — so the consumer never sees 0004's error and never re-marks the row.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from fel_workers.extraction.errors import ExtractionError
from fel_workers.extraction.persist import (
    TERMINAL_RUN_STATUSES,
    MemoryPersistStore,
    PostgresPersistStore,
    RunAlreadyTerminal,
)

from .test_postgres_crash_resume import (
    _ORG,
    _request,
    _seed_parents,
    _seed_run,
    ensure_extraction_database,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)

RUN = "0f0f0f0f-0000-4000-8000-000000000146"
ORG = "0f0f0f0f-0000-4000-8000-0000000000c1"
TERMINAL = ("succeeded", "failed", "cancelled")
EVERY_STATUS = ("queued", "running", "waiting_review", *TERMINAL)


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


def test_terminal_set_matches_0004_and_the_queue_contract() -> None:
    assert TERMINAL_RUN_STATUSES == frozenset(TERMINAL)


def test_run_already_terminal_is_a_typed_extraction_error() -> None:
    err = RunAlreadyTerminal(run_id=RUN, status="failed")
    assert isinstance(err, ExtractionError)
    assert err.code == "run_terminal"
    assert err.run_id == RUN
    assert err.status == "failed"
    assert RUN in str(err) and "failed" in str(err)


@pytest.mark.parametrize("terminal", TERMINAL)
def test_memory_mark_running_refuses_a_terminal_run(terminal: str) -> None:
    store = MemoryPersistStore()
    store.mark_running(run_id=RUN, org_id=ORG)
    store.set_run_status(run_id=RUN, org_id=ORG, status=terminal)

    with pytest.raises(RunAlreadyTerminal) as info:
        store.mark_running(run_id=RUN, org_id=ORG)

    assert info.value.run_id == RUN
    assert info.value.status == terminal
    assert store.run_status[RUN] == terminal, "the refused write still mutated the run"


@pytest.mark.parametrize("terminal", TERMINAL)
@pytest.mark.parametrize("next_status", EVERY_STATUS)
def test_memory_set_run_status_refuses_to_leave_a_terminal_status(
    terminal: str, next_status: str
) -> None:
    """Any update of a terminal row is refused — 0004 does not exempt no-op writes."""
    store = MemoryPersistStore()
    store.mark_running(run_id=RUN, org_id=ORG)
    store.set_run_status(run_id=RUN, org_id=ORG, status=terminal)

    with pytest.raises(RunAlreadyTerminal) as info:
        store.set_run_status(run_id=RUN, org_id=ORG, status=next_status)

    assert info.value.status == terminal
    assert store.run_status[RUN] == terminal


def test_memory_non_terminal_lifecycle_is_unaffected() -> None:
    """Crash-resume of a run still ``running`` must keep working (#146 acceptance 4)."""
    store = MemoryPersistStore()
    store.mark_running(run_id=RUN, org_id=ORG)
    store.mark_running(run_id=RUN, org_id=ORG)  # resume of a running run
    store.set_run_status(run_id=RUN, org_id=ORG, status="waiting_review")
    store.set_run_status(run_id=RUN, org_id=ORG, status="succeeded")
    assert store.run_status[RUN] == "succeeded"
    # An unknown run is treated as queued, as it always was.
    other = MemoryPersistStore()
    other.set_run_status(run_id=RUN, org_id=ORG, status="cancelled")
    assert other.run_status[RUN] == "cancelled"


@requires_db
@pytest.mark.parametrize("terminal", TERMINAL)
def test_postgres_mark_running_refuses_a_terminal_run_before_the_trigger(
    extraction_db_url: str, terminal: str
) -> None:
    """The typed refusal, not 0004's RaiseException, and the row is untouched."""
    # Fresh id per test: 0004 makes the row permanent, so a fixed id would
    # collide with itself on the next run of the suite.
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, request)
        store = PostgresPersistStore(conn)
        store.mark_running(run_id=request.run_id, org_id=_ORG)
        store.set_run_status(run_id=request.run_id, org_id=_ORG, status=terminal)
        before = conn.execute(
            "SELECT status, started_at, finished_at FROM extraction_runs WHERE id = %s",
            (request.run_id,),
        ).fetchone()

        with pytest.raises(RunAlreadyTerminal) as info:
            store.mark_running(run_id=request.run_id, org_id=_ORG)

        after = conn.execute(
            "SELECT status, started_at, finished_at FROM extraction_runs WHERE id = %s",
            (request.run_id,),
        ).fetchone()

    assert info.value.run_id == request.run_id
    assert info.value.status == terminal
    assert not isinstance(info.value, psycopg.Error)
    assert before is not None and before[0] == terminal
    assert after == before, "mark_running touched a terminal row"


@requires_db
@pytest.mark.parametrize("terminal", TERMINAL)
def test_postgres_set_run_status_on_a_terminal_run_is_what_0004_rejects(
    extraction_db_url: str, terminal: str
) -> None:
    """Characterisation of the trigger the memory guard mirrors (pre-existing)."""
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, request)
        store = PostgresPersistStore(conn)
        store.mark_running(run_id=request.run_id, org_id=_ORG)
        store.set_run_status(run_id=request.run_id, org_id=_ORG, status=terminal)
        with pytest.raises(psycopg.errors.RaiseException, match="terminal extraction run"):
            store.set_run_status(run_id=request.run_id, org_id=_ORG, status="failed")
