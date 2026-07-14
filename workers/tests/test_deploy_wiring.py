"""Deployment-shaped tests for the worker entrypoint (PR #85, rounds 2-3).

Each test runs the REAL service invocation — ``python -m fel_workers run``,
exactly what `infra/railway/worker.json` starts — in a subprocess with a
scrubbed, production-like environment (FEL_DATABASE_URL plus only the mode
variables under test) and asserts the fail-closed configuration matrix
resolves BEFORE any database connection is attempted:

- no provider mode           -> exit 2, names FEL_SEC_LIVE + FEL_MOCK_SMOKE
- both modes (any spelling)  -> exit 2 (ambiguous)
- unrecognized flag value    -> exit 2 naming the variable and the value
  (typos like "ture" fail closed; "0" is NOT treated as unset — explicit
  unset means removing the variable, and rejecting "0" avoids guessing
  whether the operator meant "off" or fat-fingered "on")
- FEL_MOCK_SMOKE=1           -> passes the mode gate (then fails on the
  dummy DB)
- FEL_SEC_LIVE=TRUE          -> accepted spelling; live path proceeds to
  its next requirement (FEL_SEC_USER_AGENT)
- live without storage       -> exit 2 naming FEL_STORAGE_DIR
- live+storage, no UA        -> exit 2 naming FEL_SEC_USER_AGENT
- live+storage, degenerate UA ('@', 'x@', 'ops@example', no contact)
                             -> exit 2 (contact-address pattern required)
- ``run --help``             -> exit 0 with usage, even fully unconfigured

The exit-2 DSN points at an unroutable TEST-NET-3 host: if the entrypoint
ever dialed it, the run would surface a psycopg OperationalError traceback
instead of the clean configuration exit these tests assert — the
no-Traceback/no-OperationalError checks are the dial-proof. The subprocess
timeout below is hang protection only, not a performance assertion.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Unroutable (TEST-NET-3, RFC 5737): must never be dialed by exit-2 paths.
UNROUTABLE_DSN = "postgresql://fel:fel@203.0.113.1:5432/fel?connect_timeout=2"
# Immediately-refused loopback port: for the path that SHOULD reach the DB.
REFUSED_DSN = "postgresql://fel:fel@127.0.0.1:1/fel?connect_timeout=2"

VALID_UA = "financial-evidence-lab worker (ops@example.com)"

# Passed through from the parent environment when set: PATH/HOME/LANG for
# the interpreter, plus the variables that interpreter and shared-library
# resolution (venvs, conda, pyenv, non-default libpq) may need outside
# GitHub CI. None of them carries FEL_* configuration, so the environment
# stays production-shaped where it matters.
_PASSTHROUGH_VARS = (
    "PATH",
    "HOME",
    "LANG",
    "LD_LIBRARY_PATH",
    "VIRTUAL_ENV",
    "PYTHONHOME",
    "CONDA_PREFIX",
)


def _run_entrypoint(
    mode_env: dict[str, str],
    dsn: str = UNROUTABLE_DSN,
    args: tuple[str, ...] = ("--max-iterations", "1"),
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m fel_workers run`` with a scrubbed environment.

    The environment is built from scratch (not inherited): the passthrough
    variables above, PYTHONPATH so the subprocess resolves fel_workers and
    fel_providers the same way pytest does, the dummy DSN, and the mode
    variables under test. Nothing else — production-like.
    """
    env = {key: os.environ[key] for key in _PASSTHROUGH_VARS if key in os.environ}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT / "workers" / "src"), str(_REPO_ROOT / "packages" / "providers")]
    )
    env["FEL_DATABASE_URL"] = dsn
    env.update(mode_env)
    return subprocess.run(
        [sys.executable, "-m", "fel_workers", "run", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,  # hang protection only — not a wall-clock assertion
    )


def _assert_config_exit_no_db(proc: subprocess.CompletedProcess[str]) -> None:
    """Exit 2 from configuration validation, with zero database activity."""
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    # A dialed unroutable DSN would raise psycopg.OperationalError (traceback,
    # exit 1) after burning the connect timeout — neither may appear here.
    assert "OperationalError" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr


def test_no_mode_exits_2_naming_both_options() -> None:
    proc = _run_entrypoint({})
    _assert_config_exit_no_db(proc)
    assert "FEL_SEC_LIVE" in proc.stderr
    assert "FEL_MOCK_SMOKE" in proc.stderr
    assert "production" in proc.stderr  # warns mock must never hit production


def test_both_modes_exit_2_as_ambiguous() -> None:
    proc = _run_entrypoint({"FEL_SEC_LIVE": "1", "FEL_MOCK_SMOKE": "1"})
    _assert_config_exit_no_db(proc)
    assert "ambiguous" in proc.stderr


def test_both_modes_ambiguous_across_accepted_spellings() -> None:
    """The ambiguity gate must hold across every accepted truthy spelling —
    FEL_SEC_LIVE=true + FEL_MOCK_SMOKE=1 is the corruption scenario where a
    lenient parser would silently drop one mode and run the other."""
    proc = _run_entrypoint({"FEL_SEC_LIVE": "true", "FEL_MOCK_SMOKE": "1"})
    _assert_config_exit_no_db(proc)
    assert "ambiguous" in proc.stderr


def test_uppercase_true_is_accepted_and_live_path_proceeds() -> None:
    """FEL_SEC_LIVE=TRUE selects live mode (normalized parsing) and the run
    proceeds to live mode's next requirement — the SEC identity — rather
    than being misread as unset or rejected as a typo."""
    proc = _run_entrypoint({"FEL_SEC_LIVE": "TRUE"})
    _assert_config_exit_no_db(proc)
    assert "unrecognized" not in proc.stderr
    assert "provider mode is not configured" not in proc.stderr
    assert "FEL_SEC_USER_AGENT" in proc.stderr


def test_typo_flag_value_exits_2_unrecognized() -> None:
    """A typo like FEL_SEC_LIVE=ture must fail closed with a message naming
    the variable and the received value — not silently read as unset."""
    proc = _run_entrypoint({"FEL_SEC_LIVE": "ture"})
    _assert_config_exit_no_db(proc)
    assert "unrecognized" in proc.stderr
    assert "FEL_SEC_LIVE" in proc.stderr
    assert "ture" in proc.stderr
    assert "1/true/yes/on" in proc.stderr


def test_zero_is_rejected_not_treated_as_unset() -> None:
    """FEL_MOCK_SMOKE=0 exits 2 as an unrecognized value. Deliberate choice:
    explicit unset means REMOVING the variable; rejecting "0" avoids
    guessing whether the operator meant "off" or mistyped an opt-in."""
    proc = _run_entrypoint({"FEL_MOCK_SMOKE": "0"})
    _assert_config_exit_no_db(proc)
    assert "unrecognized" in proc.stderr
    assert "FEL_MOCK_SMOKE" in proc.stderr


def test_mock_smoke_opt_in_passes_the_mode_gate() -> None:
    """FEL_MOCK_SMOKE=1 gets PAST the mode gate: the run proceeds to the
    database step and fails there (refused loopback port), not on mode."""
    proc = _run_entrypoint({"FEL_MOCK_SMOKE": "1"}, dsn=REFUSED_DSN)
    assert proc.returncode != 2, (proc.stdout, proc.stderr)
    assert "provider mode is not configured" not in proc.stderr
    # Evidence it reached the connection attempt against the dummy DSN.
    assert "OperationalError" in proc.stderr or "connection" in proc.stderr.lower(), proc.stderr


def test_run_help_exits_0_even_unconfigured() -> None:
    """``run --help`` must honor the argparse contract (usage on stdout,
    exit 0) BEFORE the mode gate — an operator asking an unconfigured
    service for usage must not get the exit-2 configuration error."""
    proc = _run_entrypoint({}, args=("--help",))
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "usage" in proc.stdout.lower(), proc.stdout
    assert "--max-iterations" in proc.stdout, proc.stdout


def test_live_without_storage_exits_2() -> None:
    proc = _run_entrypoint({"FEL_SEC_LIVE": "1", "FEL_SEC_USER_AGENT": VALID_UA})
    _assert_config_exit_no_db(proc)
    assert "FEL_STORAGE_DIR" in proc.stderr


def test_live_with_storage_but_no_user_agent_exits_2(tmp_path: pathlib.Path) -> None:
    proc = _run_entrypoint({"FEL_SEC_LIVE": "1", "FEL_STORAGE_DIR": str(tmp_path / "blobs")})
    _assert_config_exit_no_db(proc)
    assert "FEL_SEC_USER_AGENT" in proc.stderr


@pytest.mark.parametrize(
    "bad_ua",
    [
        "fel-worker-no-contact",  # no '@' at all
        "@",  # bare marker, no local part or domain
        "x@",  # no domain
        "ops@example",  # domain without a dotted TLD
    ],
)
def test_live_with_degenerate_user_agent_exits_2(bad_ua: str, tmp_path: pathlib.Path) -> None:
    """A User-Agent without a plausible contact address is rejected — a bare
    or dotless '@' gives the SEC no way to reach the operator."""
    proc = _run_entrypoint(
        {
            "FEL_SEC_LIVE": "1",
            "FEL_STORAGE_DIR": str(tmp_path / "blobs"),
            "FEL_SEC_USER_AGENT": bad_ua,
        }
    )
    _assert_config_exit_no_db(proc)
    assert "FEL_SEC_USER_AGENT" in proc.stderr
    assert "@" in proc.stderr


def test_live_with_contactable_user_agent_passes_ua_gate(tmp_path: pathlib.Path) -> None:
    """A well-formed identity passes the UA gate: with storage configured the
    run proceeds to the database step (refused loopback), not a config exit."""
    proc = _run_entrypoint(
        {
            "FEL_SEC_LIVE": "1",
            "FEL_STORAGE_DIR": str(tmp_path / "blobs"),
            "FEL_SEC_USER_AGENT": VALID_UA,
        },
        dsn=REFUSED_DSN,
    )
    assert proc.returncode != 2, (proc.stdout, proc.stderr)
    assert "FEL_SEC_USER_AGENT" not in proc.stderr
    assert "OperationalError" in proc.stderr or "connection" in proc.stderr.lower(), proc.stderr
