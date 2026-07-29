"""Run usage accounting must never regress under concurrent workers.

``record_usage`` issued a blind ``SET calls_used = %s, ...``, so whichever
worker wrote last decided the run's entire accounting — a worker holding a
stale snapshot silently erased another's spend.

Two workers on one run is not hypothetical. ``LeaseHeartbeat._run`` swallows a
heartbeat CONNECTION failure without setting ``lease_lost`` (``consumer.py``:
"a heartbeat *connection* failure is not proof of loss"), so a worker whose
heartbeat connection dies keeps running while the reaper requeues its job and a
second worker claims it. Both then write usage for the same run. The fenced
terminal write decides which one's RESULT counts, but nothing fenced the usage
counters, and those counters are what ``load_usage`` feeds into the next
attempt's ``RunBudget`` — so a clobbered total re-grants budget that was
already spent, which is the one thing ADR-0007's caps exist to prevent.

The counters are cumulative per run (``run_extraction_workflow`` seeds its
budget with ``max(in-memory, carried)``), so the safe merge is monotonic, not
additive: summing would double-count the carried usage each worker already
loaded. ``GREATEST`` in SQL also makes it a single server-side read-modify-write
under the row lock, where a Python-side ``load_usage``/``max``/``SET`` would
still race between the read and the write.
"""

from __future__ import annotations

import os
import threading
import uuid
from decimal import Decimal

import psycopg
import pytest

from fel_workers.extraction.persist import PostgresPersistStore, UsageSnapshot

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


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


def _usage(conn: psycopg.Connection, run_id: str) -> tuple[int, int, int, Decimal]:
    row = conn.execute(
        """
        SELECT calls_used, input_tokens_used, output_tokens_used, cost_usd
          FROM extraction_runs WHERE id = %s
        """,
        (run_id,),
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2], row[3]


@requires_db
def test_a_stale_worker_cannot_erase_recorded_usage(extraction_db_url: str) -> None:
    """A behind-the-times snapshot must not lower the run's counters.

    The second write here is the one a worker still holding an early snapshot
    would issue. Under the blind ``SET`` it became the run's official spend, so
    the next attempt's budget was computed from usage that had already been
    consumed.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, request)
        store = PostgresPersistStore(conn)
        store.mark_running(run_id=request.run_id, org_id=_ORG)

        store.record_usage(
            run_id=request.run_id,
            org_id=_ORG,
            usage=UsageSnapshot(
                calls_used=5,
                input_tokens_used=4000,
                output_tokens_used=900,
                cost_usd=Decimal("1.20"),
            ),
        )
        store.record_usage(
            run_id=request.run_id,
            org_id=_ORG,
            usage=UsageSnapshot(
                calls_used=3,
                input_tokens_used=1000,
                output_tokens_used=200,
                cost_usd=Decimal("0.40"),
            ),
        )
        calls, input_tokens, output_tokens, cost = _usage(conn, request.run_id)

    assert calls == 5, "a stale worker erased 2 recorded calls of budget"
    assert input_tokens == 4000, "a stale worker erased recorded input tokens"
    assert output_tokens == 900, "a stale worker erased recorded output tokens"
    assert cost == Decimal("1.20"), "a stale worker erased recorded spend"


@requires_db
def test_concurrent_writers_do_not_lose_each_others_usage(extraction_db_url: str) -> None:
    """The merge must happen in the database, not between two Python statements.

    The second connection's UPDATE is issued while the first still holds the row
    lock inside an open transaction, so it blocks and then re-evaluates against
    the committed value. A read-then-write merge in Python would read the
    pre-update row and write the lower total.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as setup:
        setup.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(setup)
        _seed_run(setup, request)
        PostgresPersistStore(setup).mark_running(run_id=request.run_id, org_id=_ORG)

    blocked_started = threading.Event()
    error: list[BaseException] = []

    def _slow_writer() -> None:
        """Writes the LOWER total, while the higher one is uncommitted."""
        try:
            with psycopg.connect(extraction_db_url, autocommit=True) as conn:
                conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
                blocked_started.set()
                PostgresPersistStore(conn).record_usage(
                    run_id=request.run_id,
                    org_id=_ORG,
                    usage=UsageSnapshot(
                        calls_used=2,
                        input_tokens_used=500,
                        output_tokens_used=100,
                        cost_usd=Decimal("0.10"),
                    ),
                )
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assertion below
            error.append(exc)

    with psycopg.connect(extraction_db_url) as holder:
        holder.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        with holder.transaction():
            PostgresPersistStore(holder).record_usage(
                run_id=request.run_id,
                org_id=_ORG,
                usage=UsageSnapshot(
                    calls_used=7,
                    input_tokens_used=6000,
                    output_tokens_used=1500,
                    cost_usd=Decimal("1.90"),
                ),
            )
            writer = threading.Thread(target=_slow_writer)
            writer.start()
            # Let the second writer reach (and block on) the locked row before
            # this transaction commits.
            blocked_started.wait(timeout=5)
            writer.join(timeout=1)
        writer.join(timeout=10)

    assert not error, error
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        calls, input_tokens, output_tokens, cost = _usage(conn, request.run_id)

    assert calls == 7, "a concurrent writer clobbered the higher call count"
    assert input_tokens == 6000
    assert output_tokens == 1500
    assert cost == Decimal("1.90"), "a concurrent writer clobbered the higher spend"
