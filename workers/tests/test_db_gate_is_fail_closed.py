"""The DB gate must fail closed when CI says a database is required.

Both DB-gated suites skip themselves when ``TEST_DATABASE_URL`` is unset. That
is right for a laptop and wrong for CI: if the variable is ever dropped,
renamed, or scoped to the wrong job, roughly 218 tests stop running and the
check still reports green (#202). ``FEL_REQUIRE_DB=1`` turns that silence into
a collection error.

These tests drive pytest in a subprocess because the guard fires at import
time, which cannot be observed from inside an already-imported conftest.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# One representative DB-gated suite per package.
GATED_SUITES = (
    "workers/tests/extraction/test_cancelled_run_job_state.py",
    "apps/api/tests/test_costs.py",
)


def _collect(suite: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("TEST_DATABASE_URL", "FEL_REQUIRE_DB")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", suite],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("suite", GATED_SUITES)
def test_require_db_without_a_url_is_an_error(suite: str) -> None:
    """FEL_REQUIRE_DB=1 with no URL must fail loudly, not skip."""
    result = _collect(suite, {"FEL_REQUIRE_DB": "1"})
    assert result.returncode != 0, (
        f"{suite} collected successfully with FEL_REQUIRE_DB=1 and no "
        f"TEST_DATABASE_URL. The gate is still fail-open.\n{result.stdout}"
    )
    combined = result.stdout + result.stderr
    assert "FEL_REQUIRE_DB" in combined, (
        f"{suite} failed, but not with the guard's message, so the failure does "
        f"not tell an operator what went wrong:\n{combined}"
    )


@pytest.mark.parametrize("suite", GATED_SUITES)
def test_without_require_db_a_missing_url_still_skips(suite: str) -> None:
    """The laptop path is unchanged: no flag, no URL, collection succeeds."""
    result = _collect(suite, {})
    assert result.returncode == 0, (
        f"{suite} stopped collecting without TEST_DATABASE_URL. The guard must "
        f"only bite when FEL_REQUIRE_DB=1.\n{result.stdout}{result.stderr}"
    )
