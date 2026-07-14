"""Process entrypoint for the worker service (`python -m fel_workers`).

Two modes:

- ``python -m fel_workers`` — heartbeat loop (default, unchanged): a real,
  observable process for the Railway worker service.
- ``python -m fel_workers run [--max-iterations N] [--queue NAME]`` — the
  job-queue consumer: claims queued jobs (FEL_DATABASE_URL) and dispatches
  SEC discovery/fetch work through :mod:`fel_workers.consumer`. Provider
  bindings default to the deterministic mocks; set ``FEL_SEC_LIVE=1`` to
  bind the live EDGAR client (fair-access compliant) — live mode REQUIRES
  ``FEL_STORAGE_DIR`` and binds durable local-disk storage
  (:class:`fel_workers.storage.LocalDirStorageProvider`), because pairing
  live ingestion with in-memory mock storage would persist storage keys in
  the database while the blobs die with the process, leaving citations
  unresolvable. ``--max-iterations`` bounds the loop for tests/one-shot
  drains.
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

    Mock mode (default): deterministic mocks, no durability required.
    Live mode (``FEL_SEC_LIVE=1``): fails closed unless ``FEL_STORAGE_DIR``
    is set — live ingestion with in-memory mock storage would record
    storage_key/canonical_text_key rows whose blobs vanish with the process,
    silently breaking citation resolution. Raises ``RuntimeError`` naming
    both variables when the pairing is invalid.
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
    return LiveSecClient(), LocalDirStorageProvider(storage_dir)


def run_main(argv: list[str]) -> int:
    """Run the job consumer against FEL_DATABASE_URL."""
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
        raise SystemExit(run_main(sys.argv[2:]))
    raise SystemExit(main())
