"""Process entrypoint for the worker service (`python -m fel_workers`).

Two modes:

- ``python -m fel_workers`` — heartbeat loop (default, unchanged): a real,
  observable process for the Railway worker service.
- ``python -m fel_workers run [--max-iterations N] [--queue NAME]`` — the
  job-queue consumer: claims queued jobs (FEL_DATABASE_URL) and dispatches
  SEC discovery/fetch work through :mod:`fel_workers.consumer`. Provider
  mode is EXPLICIT and fails closed (see :func:`run_entry`): exactly one of

  - ``FEL_SEC_LIVE=1`` — live EDGAR client (fair-access compliant).
    REQUIRES ``FEL_STORAGE_DIR`` (durable local-disk storage via
    :class:`fel_workers.storage.LocalDirStorageProvider`, because pairing
    live ingestion with in-memory mock storage would persist storage keys
    in the database while the blobs die with the process, leaving
    citations unresolvable) and ``FEL_SEC_USER_AGENT`` (the deployment's
    SEC fair-access identity; the in-code default is for library/tests
    only).
  - ``FEL_MOCK_SMOKE=1`` — deterministic mock providers, an explicit
    NON-PRODUCTION smoke option: mock runs claim real queued jobs and
    complete them with fabricated output, so they must never point at a
    production database or queue.

  With neither (or both) set, the process exits with status 2 before any
  database connection is attempted. ``--max-iterations`` bounds the loop
  for tests/one-shot drains.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from types import FrameType
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from fel_providers.interfaces import SecClient, StorageProvider

log = logging.getLogger("fel_workers")

_running = True


def _request_stop(signum: int, frame: FrameType | None) -> None:
    global _running
    _running = False


def _configure() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","logger":"%(name)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)


def main(max_beats: int | None = None, interval_seconds: float = 30.0) -> int:
    """Log a heartbeat until stopped (SIGTERM/SIGINT) or max_beats is reached."""
    _configure()
    log.info("worker started in heartbeat mode; use 'run' for the job consumer")
    beats = 0
    while _running and (max_beats is None or beats < max_beats):
        log.info("heartbeat %d", beats)
        beats += 1
        if _running and (max_beats is None or beats < max_beats):
            time.sleep(interval_seconds)
    log.info("worker stopped after %d heartbeats", beats)
    return 0


def parse_run_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m fel_workers run")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--queue", default="ingestion")
    return parser.parse_args(argv)


def build_run_providers() -> tuple[SecClient, StorageProvider]:
    """Bind (sec, storage) providers for run mode from the environment.

    Direct (library/test) calls default to the deterministic mocks when
    ``FEL_SEC_LIVE`` is unset; the DEPLOYMENT path never relies on that
    default — :func:`run_entry` gates provider mode explicitly (exit 2
    unless exactly one of ``FEL_SEC_LIVE=1``/``FEL_MOCK_SMOKE=1`` is set)
    before this function is reached.

    Live mode (``FEL_SEC_LIVE=1``): fails closed unless ``FEL_STORAGE_DIR``
    is set — live ingestion with in-memory mock storage would record
    storage_key/canonical_text_key rows whose blobs vanish with the process,
    silently breaking citation resolution. Raises ``RuntimeError`` naming
    both variables when the pairing is invalid. When ``FEL_SEC_USER_AGENT``
    is set, it is passed to :class:`LiveSecClient` as the SEC fair-access
    identity (required on the deployment path, enforced by
    :func:`run_entry`; the in-code default identity is for library/tests
    only).
    """
    from fel_providers.mocks import MockSecClient, MockStorageProvider
    from fel_workers.ingestion.sec_client import LiveSecClient
    from fel_workers.storage import LocalDirStorageProvider

    if os.environ.get("FEL_SEC_LIVE") != "1":
        return MockSecClient(), MockStorageProvider()
    storage_dir = os.environ.get("FEL_STORAGE_DIR")
    if not storage_dir:
        raise RuntimeError(
            "FEL_SEC_LIVE=1 requires FEL_STORAGE_DIR: live SEC ingestion must"
            " write blobs to durable storage (LocalDirStorageProvider), not the"
            " in-memory mock — otherwise persisted storage keys become"
            " unresolvable when the process exits. Set FEL_STORAGE_DIR to a"
            " writable directory or unset FEL_SEC_LIVE."
        )
    user_agent = os.environ.get("FEL_SEC_USER_AGENT", "").strip()
    sec = LiveSecClient(user_agent=user_agent) if user_agent else LiveSecClient()
    return sec, LocalDirStorageProvider(storage_dir)


def resolve_provider_mode() -> str:
    """Resolve the explicit provider mode: ``"live"`` or ``"mock"``.

    The consumer never guesses: an unconfigured worker attached to a real
    database/queue with mock providers would mark real ``sec_discovery``
    jobs successful with empty output and could persist mock bytes under
    real accessions. Raises ``RuntimeError`` when neither — or both — of
    ``FEL_SEC_LIVE=1`` / ``FEL_MOCK_SMOKE=1`` is set.
    """
    live = os.environ.get("FEL_SEC_LIVE") == "1"
    mock = os.environ.get("FEL_MOCK_SMOKE") == "1"
    if live and mock:
        raise RuntimeError(
            "both FEL_SEC_LIVE=1 and FEL_MOCK_SMOKE=1 are set — provider mode"
            " is ambiguous; set exactly one and restart."
        )
    if live:
        return "live"
    if mock:
        return "mock"
    raise RuntimeError(
        "provider mode is not configured — refusing to start. Set"
        " FEL_SEC_LIVE=1 for live SEC ingestion (also requires"
        " FEL_STORAGE_DIR and FEL_SEC_USER_AGENT), or FEL_MOCK_SMOKE=1 to"
        " explicitly opt in to the deterministic mock providers. WARNING:"
        " mock mode claims real queued jobs and completes them with"
        " fabricated output; it must never point at a production database"
        " or queue."
    )


def validate_live_user_agent() -> str:
    """Return the deployment SEC identity from ``FEL_SEC_USER_AGENT``.

    Live mode must not fall back to the in-code default User-Agent (a
    personal contact literal kept only for library/tests). Raises
    ``RuntimeError`` unless the value is non-empty and carries a contact
    marker (``@``).
    """
    user_agent = os.environ.get("FEL_SEC_USER_AGENT", "").strip()
    if not user_agent or "@" not in user_agent:
        raise RuntimeError(
            "FEL_SEC_LIVE=1 requires FEL_SEC_USER_AGENT: an SEC fair-access"
            " identity of the shape 'org-or-app name (contact@example.com)'"
            " — it must be non-empty and contain a contact address ('@')."
            " The in-code default identity is for library/tests only; the"
            " production identity always comes from this variable."
        )
    return user_agent


def run_entry(argv: list[str]) -> int:
    """Deployment entrypoint for ``python -m fel_workers run``.

    Fails closed BEFORE any database connection: enforces an explicit
    provider mode (:func:`resolve_provider_mode`) and, in live mode, a
    configured SEC identity (:func:`validate_live_user_agent`), then
    delegates to :func:`run_main`. Exits 2 on any configuration error.
    """
    _configure()
    try:
        if resolve_provider_mode() == "live":
            validate_live_user_agent()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    return run_main(argv)


def run_main(argv: list[str]) -> int:
    """Run the job consumer against FEL_DATABASE_URL.

    In-process helper: assumes the provider mode was already gated by
    :func:`run_entry` (the only deployment path). Called directly, it keeps
    the legacy library/test contract of defaulting to mock providers via
    :func:`build_run_providers` — never expose this function as a service
    entrypoint without the :func:`run_entry` gate in front of it.
    """
    from fel_workers.consumer import run_worker

    _configure()
    args = parse_run_args(argv)
    database_url = os.environ.get("FEL_DATABASE_URL")
    if not database_url:
        log.error("FEL_DATABASE_URL is not configured")
        return 2
    try:
        sec, storage = build_run_providers()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    with psycopg.connect(database_url, autocommit=True) as conn:
        completed = run_worker(
            conn,
            storage,
            sec,
            queue_name=args.queue,
            max_iterations=args.max_iterations,
            should_continue=lambda: _running,
        )
    log.info("worker run mode finished; %d job(s) completed", completed)
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        raise SystemExit(run_entry(sys.argv[2:]))
    raise SystemExit(main())
