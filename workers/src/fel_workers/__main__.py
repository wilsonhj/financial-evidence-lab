"""Process entrypoint for the worker service (`python -m fel_workers`).

Runs a heartbeat loop so the Railway worker service has a real, observable
process from day one. The PostgreSQL job-queue consumer replaces the loop
body when M0-PLATFORM (T0002/T0008) lands; the entrypoint contract stays
`python -m fel_workers`.
"""

from __future__ import annotations

import logging
import signal
import time
from types import FrameType

log = logging.getLogger("fel_workers")

_running = True


def _request_stop(signum: int, frame: FrameType | None) -> None:
    global _running
    _running = False


def main(max_beats: int | None = None, interval_seconds: float = 30.0) -> int:
    """Log a heartbeat until stopped (SIGTERM/SIGINT) or max_beats is reached."""
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","logger":"%(name)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    log.info("worker started; job-queue consumer arrives with M0-PLATFORM")
    beats = 0
    while _running and (max_beats is None or beats < max_beats):
        log.info("heartbeat %d", beats)
        beats += 1
        if _running and (max_beats is None or beats < max_beats):
            time.sleep(interval_seconds)
    log.info("worker stopped after %d heartbeats", beats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
