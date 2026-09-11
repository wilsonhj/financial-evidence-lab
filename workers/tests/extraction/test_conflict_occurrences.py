"""ADR-0024: new-run conflict occurrences and durable membership races."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.hashing import hash_json, sha256_hex
from fel_workers.extraction.persist import PostgresPersistStore
from fel_workers.extraction.types import ConflictDraft, ProposalDraft

from .test_postgres_crash_resume import (
    _ORG,
    _USER,
    _WORKSPACE,
    _request,
    _seed_parents,
    _seed_run,
    ensure_extraction_database,
)

_ABSENT = object()


@pytest.fixture(scope="module")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(url)


def seed(conn: psycopg.Connection, policy: Any = "run/v1", count: int = 2) -> tuple[str, list[str]]:
    _seed_parents(conn)
    request = _request(str(uuid4()))
    manifest = dict(request.input_manifest)
    if policy is not _ABSENT:
        manifest["conflict_occurrence_policy"] = policy
    request = replace(request, input_manifest=manifest, input_hash=hash_json(manifest))
    _seed_run(conn, request)
    store = PostgresPersistStore(conn)
    store.mark_running(run_id=request.run_id, org_id=_ORG)
    drafts = [
        ProposalDraft(
            kind="kpi",
            metric_id="arr",
            payload={"value": str(i)},
            raw_payload_hash=sha256_hex(str(i)),
            definition_hash=sha256_hex("ARR"),
            comparability_key={},
        )
        for i in range(count)
    ]
    store.persist_proposals(
        run_id=request.run_id, org_id=_ORG, workspace_id=_WORKSPACE, drafts=drafts
    )
    return request.run_id, [str(d.id) for d in drafts]


def persist(conn: psycopg.Connection, key: str, members: list[str]) -> str:
    rows = PostgresPersistStore(conn).persist_conflicts(
        org_id=_ORG,
        workspace_id=_WORKSPACE,
        drafts=[
            ConflictDraft(
                conflict_key=key, reason_codes=["value_disagreement"], member_proposal_ids=members
            )
        ],
    )
    return str(rows[0].id)


def resolve(conn: psycopg.Connection, group: str) -> None:
    conn.execute(
        "UPDATE extraction_conflicts SET status='resolved', resolved_by=%s,"
        " resolved_at=now(), resolution_note='Selected cited winner' WHERE id=%s",
        (_USER, group),
    )


def test_resolved_parent_child_gets_independent_group_and_retry(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        parent, first = seed(conn)
        key = sha256_hex(str(uuid4()))
        original = persist(conn, key, first)
        resolve(conn, original)
        child, second = seed(conn)
        try:
            new = persist(conn, key, second)
        except StepFailed as exc:
            pytest.fail(f"child rerun inherited its parent's resolved occurrence: {exc}")
        assert new != original
        assert persist(conn, key, second) == new
        rows = conn.execute(
            "SELECT occurrence_run_id, status, resolved_by, conflict_key"
            " FROM extraction_conflicts WHERE id IN (%s,%s) ORDER BY status",
            (original, new),
        ).fetchall()
        assert {str(r[0]): (r[1], str(r[2]) if r[2] else None, r[3]) for r in rows} == {
            parent: ("resolved", _USER, key),
            child: ("open", None, key),
        }
        assert (
            conn.execute(
                "SELECT count(*) FROM extraction_conflict_members WHERE conflict_id=%s", (new,)
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize("policy", [None, 0, [], {}, "unknown/v1"])
def test_present_invalid_policy_fails_closed(db_url: str, policy: Any) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        _, members = seed(conn, policy)
        with pytest.raises(StepFailed, match="policy"):
            persist(conn, sha256_hex(str(uuid4())), members)


def test_legacy_absent_policy_shares_open_key_and_preserves_terminal_guard(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        _, first = seed(conn, _ABSENT)
        _, second = seed(conn, _ABSENT)
        key = sha256_hex(str(uuid4()))
        original = persist(conn, key, first)
        assert persist(conn, key, second) == original
        assert conn.execute(
            "SELECT occurrence_run_id FROM extraction_conflicts WHERE id=%s", (original,)
        ).fetchone() == (None,)
        resolve(conn, original)
        with pytest.raises(StepFailed, match="adjudicated"):
            persist(conn, key, second)


def test_occurrence_refuses_cross_run_or_missing_members(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        _, first = seed(conn)
        _, second = seed(conn)
        for members in ([first[0], second[0]], [first[0], str(uuid4())]):
            with pytest.raises(StepFailed):
                persist(conn, sha256_hex(str(uuid4())), members)


def test_resolved_membership_exact_retry_is_noop_but_new_member_is_refused(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        run, members = seed(conn, count=3)
        group = persist(conn, sha256_hex(str(uuid4())), members[:2])
        resolve(conn, group)
        conn.execute(
            "UPDATE extraction_runs SET status='cancelled', finished_at=now() WHERE id=%s", (run,)
        )
        insert = (
            "INSERT INTO extraction_conflict_members (conflict_id,proposal_id,org_id)"
            " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING"
        )
        conn.execute(insert, (group, members[0], _ORG))
        with pytest.raises(psycopg.Error):
            conn.execute(insert, (group, members[2], _ORG))
        assert (
            conn.execute(
                "SELECT count(*) FROM extraction_conflict_members WHERE conflict_id=%s", (group,)
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize(
    "assignment",
    [
        "status='open', resolved_by=NULL, resolved_at=NULL",
        "resolution_note='rewritten'",
        "resolved_at=now() + interval '1 second'",
        "occurrence_run_id=NULL",
    ],
)
def test_resolved_adjudication_and_occurrence_are_immutable(db_url: str, assignment: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        _, members = seed(conn)
        group = persist(conn, sha256_hex(str(uuid4())), members)
        resolve(conn, group)
        with pytest.raises(psycopg.Error):
            conn.execute(f"UPDATE extraction_conflicts SET {assignment} WHERE id=%s", (group,))


def observed_lock(observer: psycopg.Connection, pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        row = observer.execute(
            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)
        ).fetchone()
        if row and row[0] == "Lock":
            return
        time.sleep(0.01)
    pytest.fail("second connection did not visibly wait on the held PostgreSQL row lock")


def test_member_insert_waits_for_run_before_group_then_sees_resolution(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as observer:
        run, members = seed(observer, count=3)
        group = persist(observer, sha256_hex(str(uuid4())), members[:2])
        with psycopg.connect(db_url) as review, psycopg.connect(db_url) as worker:
            worker.execute("SET statement_timeout='5s'")
            review.execute("SELECT id FROM extraction_runs WHERE id=%s FOR UPDATE", (run,))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    worker.execute,
                    "INSERT INTO extraction_conflict_members (conflict_id,proposal_id,org_id)"
                    " VALUES (%s,%s,%s)",
                    (group, members[2], _ORG),
                )
                try:
                    observed_lock(observer, worker.info.backend_pid)
                    # This succeeds without deadlock only if the waiting worker has
                    # not taken group before its parent run lock.
                    resolve(review, group)
                    review.commit()
                    with pytest.raises(psycopg.Error, match="resolved|open|terminal"):
                        future.result(timeout=5)
                finally:
                    review.rollback()
                    worker.rollback()
        assert (
            observer.execute(
                "SELECT count(*) FROM extraction_conflict_members WHERE conflict_id=%s",
                (group,),
            ).fetchone()[0]
            == 2
        )


def test_member_commit_precedes_review_snapshot(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as observer:
        run, members = seed(observer, count=3)
        group = persist(observer, sha256_hex(str(uuid4())), members[:2])
        with psycopg.connect(db_url) as worker, psycopg.connect(db_url) as review:
            review.execute("SET statement_timeout='5s'")
            worker.execute(
                "INSERT INTO extraction_conflict_members (conflict_id,proposal_id,org_id)"
                " VALUES (%s,%s,%s)",
                (group, members[2], _ORG),
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    review.execute, "SELECT id FROM extraction_runs WHERE id=%s FOR UPDATE", (run,)
                )
                try:
                    observed_lock(observer, review.info.backend_pid)
                    worker.commit()
                    future.result(timeout=5)
                    actual = review.execute(
                        "SELECT proposal_id FROM extraction_conflict_members WHERE conflict_id=%s",
                        (group,),
                    ).fetchall()
                    assert {str(row[0]) for row in actual} == set(members)
                finally:
                    worker.rollback()
                    review.rollback()


def test_two_workers_upsert_same_occurrence(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as observer:
        _, members = seed(observer)
        key = sha256_hex(str(uuid4()))

        def write() -> str:
            with psycopg.connect(db_url) as conn:
                conn.execute("SET statement_timeout='5s'")
                return persist(conn, key, members)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(write)
            second = pool.submit(write)
            assert first.result(timeout=5) == second.result(timeout=5)
