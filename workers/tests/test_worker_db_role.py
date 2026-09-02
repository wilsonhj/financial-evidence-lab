"""The opt-in worker database role switch (#190, ADR-0013).

``FEL_WORKER_DB_ROLE`` is a rollout switch, not a feature flag: unset means
today's behaviour byte for byte, and set means every worker connection enters
``fel_worker`` before its first statement. Both halves are asserted here,
plus the identifier validation — the role name is interpolated into
``SET ROLE`` because Postgres takes no bind parameter there, so a value that
is not a plain identifier must raise rather than be quoted and hoped over.

The DB-gated case runs the real ``SET ROLE`` against ``TEST_DATABASE_URL``
and then proves the adopted role is actually less privileged (DELETE on jobs
is refused), which is the only way to catch a switch that silently no-ops.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest

from fel_workers.storage import apply_worker_db_role, worker_db_role

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


class _RecordingConn:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str, *args: Any) -> None:
        self.statements.append(statement)


def test_unset_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_WORKER_DB_ROLE", raising=False)
    conn = _RecordingConn()
    assert apply_worker_db_role(conn) is None
    assert conn.statements == []


def test_blank_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", "   ")
    assert worker_db_role() is None


def test_set_role_runs_once_per_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", " fel_worker ")
    conn = _RecordingConn()
    assert apply_worker_db_role(conn) == "fel_worker"
    assert conn.statements == ["SET ROLE fel_worker"]


@pytest.mark.parametrize(
    "value",
    ["fel_worker; DROP TABLE jobs", "Fel_Worker", "1worker", "fel worker", "fel-worker"],
)
def test_non_identifier_role_names_are_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", value)
    with pytest.raises(RuntimeError, match="FEL_WORKER_DB_ROLE"):
        worker_db_role()


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_adopted_role_is_actually_less_privileged(monkeypatch: pytest.MonkeyPatch) -> None:
    """SET ROLE must really take effect: a switch that no-ops would leave the
    worker running as the owner while every dashboard says otherwise."""
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", "fel_worker")
    assert TEST_DATABASE_URL is not None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        assert apply_worker_db_role(conn) == "fel_worker"
        current = conn.execute("SELECT current_user").fetchone()
        assert current is not None and current[0] == "fel_worker"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM jobs WHERE id = gen_random_uuid()")
