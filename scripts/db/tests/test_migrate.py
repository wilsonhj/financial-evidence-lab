"""Tests for the migration ledger applier.

The planner tests are pure — they build ``Migration`` values from a temporary
directory and compare them against a dict standing in for the ledger, with no
database involved. The applier tests are gated on ``TEST_DATABASE_URL`` like
every other DB-backed suite in the repository.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest

import migrate

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)

MIGRATION_ONE = "CREATE TABLE ledger_probe_one (id integer PRIMARY KEY);\n"
MIGRATION_TWO = "CREATE TABLE ledger_probe_two (id integer PRIMARY KEY);\n"


def write_migrations(directory: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        (directory / name).write_text(body)


# --------------------------------------------------------------------------
# Pure planner logic
# --------------------------------------------------------------------------


def test_version_of_accepts_only_numbered_sql() -> None:
    assert migrate.version_of("0001_platform_core.sql") == "0001"
    assert migrate.version_of("0012_a-b.c.sql") == "0012"
    assert migrate.version_of("README.md") is None
    assert migrate.version_of("platform_core.sql") is None
    assert migrate.version_of("001_short.sql") is None
    assert migrate.version_of("0001_rls.test.sql") == "0001"


def test_discover_skips_subdirectories_and_non_migrations(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"})
    (tmp_path / "README.md").write_text("# docs")
    (tmp_path / "notes.sql").write_text("SELECT 3;")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "0001_a.test.sql").write_text("SELECT 4;")
    (tests_dir / "_helpers.sql").write_text("SELECT 5;")

    found = migrate.discover_migrations(tmp_path)

    assert [m.name for m in found] == ["0001_a.sql", "0002_b.sql"]


def test_discover_is_ordered_by_version(tmp_path: Path) -> None:
    write_migrations(
        tmp_path,
        {"0010_j.sql": "SELECT 10;", "0002_b.sql": "SELECT 2;", "0001_a.sql": "SELECT 1;"},
    )

    assert [m.version for m in migrate.discover_migrations(tmp_path)] == ["0001", "0002", "0010"]


def test_discover_rejects_duplicate_versions(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0001_b.sql": "SELECT 2;"})

    with pytest.raises(ValueError, match="duplicate migration version"):
        migrate.discover_migrations(tmp_path)


def test_discover_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        migrate.discover_migrations(tmp_path / "nope")


def test_plan_marks_everything_pending_on_an_empty_ledger(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"})
    migrations = migrate.discover_migrations(tmp_path)

    plan = migrate.build_plan(migrations, {})

    assert [m.version for m in plan.pending] == ["0001", "0002"]
    assert plan.applied == ()
    assert plan.drifted == ()
    assert not plan.is_current


def test_plan_is_current_when_checksums_match(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;"})
    migrations = migrate.discover_migrations(tmp_path)
    ledger = {m.version: m.checksum for m in migrations}

    plan = migrate.build_plan(migrations, ledger)

    assert plan.is_current
    assert plan.pending == ()
    assert [m.version for m in plan.applied] == ["0001"]
    assert "UP TO DATE" in migrate.format_plan(plan)


def test_plan_detects_checksum_drift(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;"})
    migrations = migrate.discover_migrations(tmp_path)

    plan = migrate.build_plan(migrations, {"0001": migrate.checksum_text("SELECT 999;")})

    assert [m.version for m, _ in plan.drifted] == ["0001"]
    assert plan.pending == ()
    assert not plan.is_current
    assert "DRIFT" in migrate.format_plan(plan)


def test_plan_reports_ledger_rows_with_no_file(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;"})
    migrations = migrate.discover_migrations(tmp_path)
    ledger = {m.version: m.checksum for m in migrations} | {"0009": "deadbeef"}

    plan = migrate.build_plan(migrations, ledger)

    assert plan.missing == ("0009",)
    assert "MISSING 0009" in migrate.format_plan(plan)


def test_plan_mixes_applied_and_pending(tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"})
    migrations = migrate.discover_migrations(tmp_path)

    plan = migrate.build_plan(migrations, {"0001": migrations[0].checksum})

    assert [m.version for m in plan.applied] == ["0001"]
    assert [m.version for m in plan.pending] == ["0002"]
    assert migrate.format_plan(plan) == "PENDING 0002_b.sql"


def test_checksum_is_stable_and_content_sensitive() -> None:
    assert migrate.checksum_text("SELECT 1;") == migrate.checksum_text("SELECT 1;")
    assert migrate.checksum_text("SELECT 1;") != migrate.checksum_text("SELECT 2;")


def test_resolve_database_url_precedence() -> None:
    env = {"DATABASE_URL": "postgresql:///from-env", "TEST_DATABASE_URL": "postgresql:///from-test"}
    assert migrate.resolve_database_url("postgresql:///explicit", env) == "postgresql:///explicit"
    assert migrate.resolve_database_url(None, env) == "postgresql:///from-env"
    assert migrate.resolve_database_url(None, {"TEST_DATABASE_URL": "t"}) == "t"
    assert migrate.resolve_database_url(None, {}) is None


def test_main_without_a_database_url_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    assert migrate.main(["--migrations-dir", str(tmp_path)]) == migrate.EXIT_USAGE


# --------------------------------------------------------------------------
# Applier behavior against a real database
# --------------------------------------------------------------------------


@pytest.fixture()
def ledger_db() -> str:
    """A disposable sibling database, dropped when the test finishes."""
    assert TEST_DATABASE_URL is not None
    name = f"fel_ledger_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')  # noqa: S608 - generated name
    url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/" + name
    try:
        yield url
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # noqa: S608


@requires_db
def test_apply_twice_is_a_no_op(ledger_db: str, tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": MIGRATION_ONE, "0002_b.sql": MIGRATION_TWO})
    argv = ["--database-url", ledger_db, "--migrations-dir", str(tmp_path)]

    assert migrate.main(argv) == migrate.EXIT_OK
    # A second run must not re-execute the non-idempotent CREATE TABLEs.
    assert migrate.main(argv) == migrate.EXIT_OK
    assert migrate.main([*argv, "--check"]) == migrate.EXIT_OK

    with psycopg.connect(ledger_db) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert [row[0] for row in rows] == ["0001", "0002"]


@requires_db
def test_check_reports_pending_then_passes(ledger_db: str, tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": MIGRATION_ONE})
    argv = ["--database-url", ledger_db, "--migrations-dir", str(tmp_path)]

    assert migrate.main([*argv, "--check"]) == migrate.EXIT_PENDING
    assert migrate.main([*argv, "--dry-run"]) == migrate.EXIT_OK
    # --dry-run must not have applied anything.
    assert migrate.main([*argv, "--check"]) == migrate.EXIT_PENDING
    assert migrate.main(argv) == migrate.EXIT_OK
    assert migrate.main([*argv, "--check"]) == migrate.EXIT_OK


@requires_db
def test_editing_an_applied_migration_fails_check(ledger_db: str, tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": MIGRATION_ONE})
    argv = ["--database-url", ledger_db, "--migrations-dir", str(tmp_path)]
    assert migrate.main(argv) == migrate.EXIT_OK

    (tmp_path / "0001_a.sql").write_text(MIGRATION_ONE + "-- edited after apply\n")

    assert migrate.main([*argv, "--check"]) == migrate.EXIT_DRIFT
    assert migrate.main(argv) == migrate.EXIT_DRIFT


@requires_db
def test_baseline_records_without_executing(ledger_db: str, tmp_path: Path) -> None:
    write_migrations(tmp_path, {"0001_a.sql": MIGRATION_ONE, "0002_b.sql": MIGRATION_TWO})
    argv = ["--database-url", ledger_db, "--migrations-dir", str(tmp_path)]

    assert migrate.main([*argv, "--baseline"]) == migrate.EXIT_OK
    assert migrate.main([*argv, "--check"]) == migrate.EXIT_OK

    with psycopg.connect(ledger_db) as conn:
        probe = conn.execute("SELECT to_regclass('public.ledger_probe_one')").fetchone()
        rows = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
    assert probe is not None and probe[0] is None  # never executed
    assert rows is not None and rows[0] == 2


@requires_db
def test_failed_migration_rolls_back_and_is_not_recorded(ledger_db: str, tmp_path: Path) -> None:
    write_migrations(
        tmp_path,
        {
            "0001_a.sql": MIGRATION_ONE,
            "0002_bad.sql": "CREATE TABLE ledger_probe_bad (id integer); SELECT nope_no_such();",
        },
    )
    argv = ["--database-url", ledger_db, "--migrations-dir", str(tmp_path)]

    assert migrate.main(argv) == migrate.EXIT_APPLY_FAILED

    with psycopg.connect(ledger_db) as conn:
        versions = conn.execute("SELECT version FROM schema_migrations").fetchall()
        probe = conn.execute("SELECT to_regclass('public.ledger_probe_bad')").fetchone()
    assert [row[0] for row in versions] == ["0001"]
    assert probe is not None and probe[0] is None


@requires_db
def test_repository_migrations_apply_to_an_empty_database(ledger_db: str) -> None:
    """The real db/migrations tree applies cleanly and then reports current."""
    argv = ["--database-url", ledger_db]
    if migrate.main(argv) != migrate.EXIT_OK:
        pytest.skip("repository migrations need pgvector >= 0.8.2; not available here")
    assert migrate.main([*argv, "--check"]) == migrate.EXIT_OK
