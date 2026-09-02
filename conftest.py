"""Repository-root pytest plugin: make database-gated skips visible.

Every DB-backed suite here skips itself when ``TEST_DATABASE_URL`` is unset,
which is right for a laptop and wrong for CI — a job with a Postgres service
that quietly skips 180-odd tenant-isolation and queue tests still reports
green. This hook always prints a one-line summary of how many tests skipped
for want of a database, and fails the session when ``FEL_REQUIRE_DB_TESTS=1``
says a database was supposed to be there.

Skip reasons are matched by substring rather than by marker, because the
suites gate themselves in several equivalent ways (``pytest.mark.skipif`` at
import time, ``pytest.skip`` inside a fixture) and all of them name the
environment variable in the reason text.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pytest

# The single string every DB gate's skip reason contains. Keep any new gate's
# reason naming the variable and it is counted automatically.
DB_SKIP_MARKER = "TEST_DATABASE_URL"

REQUIRE_ENV = "FEL_REQUIRE_DB_TESTS"

_db_skips: list[tuple[str, str]] = []


def is_db_skip(reason: str) -> bool:
    """True when *reason* is a skip caused by a missing test database."""
    return DB_SKIP_MARKER in reason


def _reason_of(report: pytest.CollectReport | pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and is_db_skip(_reason_of(report)):
        _db_skips.append((report.nodeid, _reason_of(report)))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    modules = sorted({nodeid.split("::", 1)[0] for nodeid, _ in _db_skips})
    state = (
        "TEST_DATABASE_URL is set"
        if os.environ.get("TEST_DATABASE_URL")
        else "no TEST_DATABASE_URL"
    )
    terminalreporter.write_line(
        f"database-gated tests skipped: {len(_db_skips)} "
        f"across {len(modules)} module(s) ({state})"
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.environ.get(REQUIRE_ENV) != "1" or not _db_skips:
        return
    modules = sorted({nodeid.split("::", 1)[0] for nodeid, _ in _db_skips})
    listing = "\n".join(f"  - {module}" for module in modules)
    print(
        f"\nERROR: {REQUIRE_ENV}=1 but {len(_db_skips)} test(s) skipped for a "
        f"missing database, in {len(modules)} module(s):\n{listing}\n"
        "Set TEST_DATABASE_URL to a migrated Postgres (see "
        "docs/development/testing.md) or unset "
        f"{REQUIRE_ENV}."
    )
    session.exitstatus = 1
