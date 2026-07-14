"""Deployment-shaped tests for the worker entrypoint (PR #85, round 2).

Each test runs the REAL service invocation — ``python -m fel_workers run``,
exactly what `infra/railway/worker.json` starts — in a subprocess with a
scrubbed, production-like environment (FEL_DATABASE_URL plus only the mode
variables under test) and asserts the fail-closed configuration matrix
resolves BEFORE any database connection is attempted:

- no provider mode        -> exit 2, message names FEL_SEC_LIVE + FEL_MOCK_SMOKE
- both modes              -> exit 2 (ambiguous)
- FEL_MOCK_SMOKE=1        -> passes the mode gate (then fails on the dummy DB)
- live without storage    -> exit 2 naming FEL_STORAGE_DIR
- live+storage, no UA     -> exit 2 naming FEL_SEC_USER_AGENT
- live+storage, bad UA    -> exit 2 (no '@' contact marker)

The exit-2 DSN points at an unroutable TEST-NET-3 host: if the entrypoint
ever dialed it, the run would surface a psycopg connection error (and burn
the connect timeout) instead of the fast, clean configuration exit these
tests assert. No network, no real database.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Unroutable (TEST-NET-3, RFC 5737): must never be dialed by exit-2 paths.
UNROUTABLE_DSN = "postgresql://fel:fel@203.0.113.1:5432/fel?connect_timeout=2"
# Immediately-refused loopback port: for the path that SHOULD reach the DB.
REFUSED_DSN = "postgresql://fel:fel@127.0.0.1:1/fel?connect_timeout=2"

VALID_UA = "financial-evidence-lab worker (ops@example.com)"


def _run_entrypoint(
    mode_env: dict[str, str], dsn: str = UNROUTABLE_DSN
) -> tuple[subprocess.CompletedProcess[str], float]:
    """Run ``python -m fel_workers run --max-iterations 1`` scrubbed.

    The environment is built from scratch (not inherited): PATH/HOME/LANG for
    the interpreter, PYTHONPATH so the subprocess resolves fel_workers and
    fel_providers the same way pytest does, the dummy DSN, and the mode
    variables under test. Nothing else — production-like.
    """
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT / "workers" / "src"), str(_REPO_ROOT / "packages" / "providers")]
    )
    env["FEL_DATABASE_URL"] = dsn
    env.update(mode_env)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "fel_workers", "run", "--max-iterations", "1"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return proc, time.monotonic() - started


def _assert_config_exit_no_db(proc: subprocess.CompletedProcess[str], elapsed: float) -> None:
    """Exit 2 from configuration validation, with zero database activity."""
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    # A dialed unroutable DSN would raise psycopg.OperationalError (traceback,
    # exit 1) after burning the connect timeout — neither may appear here.
    assert "OperationalError" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert elapsed < 10.0, f"config exit took {elapsed:.1f}s — did it dial the DSN?"


def test_no_mode_exits_2_naming_both_options() -> None:
    proc, elapsed = _run_entrypoint({})
    _assert_config_exit_no_db(proc, elapsed)
    assert "FEL_SEC_LIVE" in proc.stderr
    assert "FEL_MOCK_SMOKE" in proc.stderr
    assert "production" in proc.stderr  # warns mock must never hit production


def test_both_modes_exit_2_as_ambiguous() -> None:
    proc, elapsed = _run_entrypoint({"FEL_SEC_LIVE": "1", "FEL_MOCK_SMOKE": "1"})
    _assert_config_exit_no_db(proc, elapsed)
    assert "ambiguous" in proc.stderr


def test_mock_smoke_opt_in_passes_the_mode_gate() -> None:
    """FEL_MOCK_SMOKE=1 gets PAST the mode gate: the run proceeds to the
    database step and fails there (refused loopback port), not on mode."""
    proc, _ = _run_entrypoint({"FEL_MOCK_SMOKE": "1"}, dsn=REFUSED_DSN)
    assert proc.returncode != 2, (proc.stdout, proc.stderr)
    assert "provider mode is not configured" not in proc.stderr
    # Evidence it reached the connection attempt against the dummy DSN.
    assert "OperationalError" in proc.stderr or "connection" in proc.stderr.lower(), proc.stderr


def test_live_without_storage_exits_2() -> None:
    proc, elapsed = _run_entrypoint({"FEL_SEC_LIVE": "1", "FEL_SEC_USER_AGENT": VALID_UA})
    _assert_config_exit_no_db(proc, elapsed)
    assert "FEL_STORAGE_DIR" in proc.stderr


def test_live_with_storage_but_no_user_agent_exits_2(tmp_path: pathlib.Path) -> None:
    proc, elapsed = _run_entrypoint(
        {"FEL_SEC_LIVE": "1", "FEL_STORAGE_DIR": str(tmp_path / "blobs")}
    )
    _assert_config_exit_no_db(proc, elapsed)
    assert "FEL_SEC_USER_AGENT" in proc.stderr


def test_live_with_malformed_user_agent_exits_2(tmp_path: pathlib.Path) -> None:
    """A User-Agent without a contact marker ('@') is rejected."""
    proc, elapsed = _run_entrypoint(
        {
            "FEL_SEC_LIVE": "1",
            "FEL_STORAGE_DIR": str(tmp_path / "blobs"),
            "FEL_SEC_USER_AGENT": "fel-worker-no-contact",
        }
    )
    _assert_config_exit_no_db(proc, elapsed)
    assert "FEL_SEC_USER_AGENT" in proc.stderr
    assert "@" in proc.stderr
