#!/usr/bin/env python3
"""Checksummed migration ledger and applier for db/migrations.

Replaces the ad-hoc ``for f in db/migrations/*.sql; do psql -f "$f"; done``
shell loops. Every applied file is recorded in a ``schema_migrations`` ledger
together with the sha256 of its contents, so:

* re-running is a no-op instead of re-applying non-idempotent SQL;
* editing a migration that was already applied is detected (checksum drift)
  and fails closed rather than silently diverging from the database;
* ``--check`` gives CI and deploys a read-only "is this database current?"
  gate.

Depends only on the standard library plus ``psycopg`` (a runtime dependency).

Exit codes
----------
0   success (applied, up to date, or the requested check passed)
1   unexpected/usage error (bad arguments, missing directory, ...)
2   ``--check``: migrations are pending
3   checksum drift: an already-applied migration file changed on disk
4   a migration failed to apply (its transaction was rolled back)
5   could not connect to the database
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_PENDING = 2
EXIT_DRIFT = 3
EXIT_APPLY_FAILED = 4
EXIT_NO_CONNECTION = 5

# ``0007_something.sql``; everything else in the directory (README.md, the
# tests/ harness subdirectory) is ignored.
MIGRATION_RE = re.compile(r"^(\d{4})_[A-Za-z0-9_.-]+\.sql$")

# Any 64-bit constant works; it only has to be stable across appliers.
ADVISORY_LOCK_KEY = 0x46454C4D49475221  # "FELMIGR!"

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class Migration:
    """A migration file on disk."""

    version: str
    path: Path
    checksum: str

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Plan:
    """What the applier intends to do, computed without touching the database."""

    pending: tuple[Migration, ...]
    applied: tuple[Migration, ...]
    drifted: tuple[tuple[Migration, str], ...]
    missing: tuple[str, ...]

    @property
    def is_current(self) -> bool:
        return not self.pending and not self.drifted


def checksum_text(text: str) -> str:
    """sha256 of a migration's contents, as lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def version_of(filename: str) -> str | None:
    """Return the ``NNNN`` version prefix of a migration filename, or None."""
    match = MIGRATION_RE.match(filename)
    return match.group(1) if match else None


def _duplicate_versions(migrations: Iterable[Migration]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for migration in migrations:
        if migration.version in seen:
            duplicates.add(migration.version)
        seen.add(migration.version)
    return duplicates


def discover_migrations(directory: Path) -> list[Migration]:
    """Enumerate ``NNNN_*.sql`` files directly under *directory*, in order.

    Subdirectories (notably ``tests/``, which holds regression harnesses that
    are not migrations) are never traversed.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {directory}")
    found: list[Migration] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        version = version_of(path.name)
        if version is None:
            continue
        found.append(
            Migration(version=version, path=path, checksum=checksum_text(path.read_text()))
        )
    duplicates = _duplicate_versions(found)
    if duplicates:
        raise ValueError("duplicate migration version(s): " + ", ".join(sorted(duplicates)))
    return found


def build_plan(migrations: Sequence[Migration], ledger: Mapping[str, str]) -> Plan:
    """Compare files on disk against the ledger rows. Pure; no I/O."""
    pending: list[Migration] = []
    applied: list[Migration] = []
    drifted: list[tuple[Migration, str]] = []
    for migration in migrations:
        recorded = ledger.get(migration.version)
        if recorded is None:
            pending.append(migration)
        elif recorded != migration.checksum:
            drifted.append((migration, recorded))
        else:
            applied.append(migration)
    on_disk = {migration.version for migration in migrations}
    missing = tuple(sorted(version for version in ledger if version not in on_disk))
    return Plan(
        pending=tuple(pending),
        applied=tuple(applied),
        drifted=tuple(drifted),
        missing=missing,
    )


def format_plan(plan: Plan) -> str:
    """Human-readable rendering of a plan, one line per interesting entry."""
    lines: list[str] = []
    for migration, recorded in plan.drifted:
        lines.append(
            f"DRIFT   {migration.name}: ledger has {recorded[:12]}, "
            f"file is {migration.checksum[:12]}"
        )
    for version in plan.missing:
        lines.append(f"MISSING {version}: recorded as applied but absent from disk")
    for migration in plan.pending:
        lines.append(f"PENDING {migration.name}")
    if not lines:
        lines.append(f"UP TO DATE ({len(plan.applied)} migration(s) applied)")
    return "\n".join(lines)


def resolve_database_url(
    explicit: str | None, environ: Mapping[str, str] | None = None
) -> str | None:
    """First of ``--database-url``, ``DATABASE_URL``, ``TEST_DATABASE_URL``."""
    if explicit:
        return explicit
    env = os.environ if environ is None else environ
    for name in ("DATABASE_URL", "TEST_DATABASE_URL"):
        value = env.get(name)
        if value:
            return value
    return None


def read_ledger(conn: psycopg.Connection[tuple[str, ...]]) -> dict[str, str]:
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {str(version): str(digest) for version, digest in rows}


def ensure_ledger(conn: psycopg.Connection[tuple[str, ...]]) -> None:
    conn.execute(LEDGER_DDL)


def acquire_lock(conn: psycopg.Connection[tuple[str, ...]]) -> None:
    """Block until this connection owns the applier advisory lock."""
    conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))


def release_lock(conn: psycopg.Connection[tuple[str, ...]]) -> None:
    conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))


def record(conn: psycopg.Connection[tuple[str, ...]], migration: Migration) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
        (migration.version, migration.checksum),
    )


def apply_migration(conn: psycopg.Connection[tuple[str, ...]], migration: Migration) -> None:
    """Apply one migration and record it in the same transaction."""
    with conn.transaction():
        conn.execute(migration.path.read_text())
        record(conn, migration)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migrate.py",
        description="Apply db/migrations with a checksummed schema_migrations ledger.",
    )
    parser.add_argument(
        "--database-url",
        help="Target database. Defaults to $DATABASE_URL, then $TEST_DATABASE_URL.",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help=f"Directory holding NNNN_*.sql files (default: {DEFAULT_MIGRATIONS_DIR}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Report status only; exit non-zero if anything is pending or drifted.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without applying anything (exits 0 unless drifted).",
    )
    mode.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "Record every pending migration as applied WITHOUT running it. For "
            "databases migrated by the old shell loop, which have no ledger."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    database_url = resolve_database_url(args.database_url)
    if not database_url:
        print(
            "error: no database URL; pass --database-url or set DATABASE_URL or TEST_DATABASE_URL",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        migrations = discover_migrations(args.migrations_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        conn: psycopg.Connection[tuple[str, ...]] = psycopg.connect(database_url, autocommit=True)
    except psycopg.OperationalError as exc:
        print(f"error: could not connect to the database: {exc}", file=sys.stderr)
        return EXIT_NO_CONNECTION

    with conn:
        ensure_ledger(conn)
        acquire_lock(conn)
        try:
            plan = build_plan(migrations, read_ledger(conn))
            print(format_plan(plan))

            if plan.drifted:
                print(
                    "error: applied migration(s) changed on disk; migrations are "
                    "append-only — correct forward with a new migration",
                    file=sys.stderr,
                )
                return EXIT_DRIFT

            if args.dry_run:
                return EXIT_OK

            if args.check:
                if plan.pending:
                    print(f"error: {len(plan.pending)} migration(s) pending", file=sys.stderr)
                    return EXIT_PENDING
                return EXIT_OK

            if args.baseline:
                with conn.transaction():
                    for migration in plan.pending:
                        record(conn, migration)
                print(
                    f"OK: baselined {len(plan.pending)} migration(s) as applied "
                    "(nothing was executed)"
                )
                return EXIT_OK

            for migration in plan.pending:
                print(f"==> applying {migration.name}")
                try:
                    apply_migration(conn, migration)
                except psycopg.Error as exc:
                    print(
                        f"error: {migration.name} failed and was rolled back: {exc}",
                        file=sys.stderr,
                    )
                    return EXIT_APPLY_FAILED
            print(f"OK: {len(plan.pending)} migration(s) applied; database is current")
            return EXIT_OK
        finally:
            release_lock(conn)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
