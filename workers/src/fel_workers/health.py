"""Worker liveness endpoint (issues #200/#203).

A worker that has stopped claiming jobs looks identical, from the outside, to
one whose queue is simply empty: the process is up, the container is
"healthy", and nothing surfaces until a tenant notices their run never
finished. This module gives the process a real liveness signal — a
last-progress timestamp the loop refreshes, and a tiny stdlib HTTP server
that turns it into a status code a platform health check can act on.

Design constraints:

* **Zero coupling to the consumer loop.** ``consumer.py`` is not edited and
  imports nothing from here. The loop's progress is observed by the
  entrypoint, which owns a :class:`Liveness` object and hands the loop a
  callback (``should_continue``) that touches it on every iteration. If the
  loop stops iterating, the timestamp stops moving.
* **Stdlib only.** :mod:`http.server` on a daemon thread; no framework, no
  dependency, nothing to add to a requirements file.
* **Fail closed on staleness, not on emptiness.** An idle worker still
  iterates (it sleeps and re-polls), so a stale timestamp means the loop
  itself is wedged or dead, which is exactly the condition worth restarting.

``GET /health`` returns ``{"status", "last_heartbeat_age_seconds", "queue"}``
with 200 while the age is within ``max_age_seconds`` and 503 once it is not.
Any other path returns 404. Before the first touch the age is measured from
the object's construction, so a process that never reaches its first
iteration goes unhealthy on schedule instead of reporting a null age
forever.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

__all__ = [
    "DEFAULT_MAX_HEARTBEAT_AGE_SECONDS",
    "HEALTH_PORT_ENV",
    "Liveness",
    "serve_health",
    "start_health_server",
]

log = logging.getLogger("fel_workers.health")

HEALTH_PORT_ENV = "FEL_WORKER_HEALTH_PORT"

# Generous next to the consumer's 1s idle poll and 15s lease heartbeat: this
# threshold answers "is the loop still turning?", not "is it fast?".
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 120.0

# All interfaces: a container health check dials the pod/container IP, not
# loopback, so binding loopback would fail every probe. The endpoint serves
# one read-only status document and no tenant data; exposure is bounded by
# the platform network, exactly as it is for the API process (which is
# started with `--host 0.0.0.0` in infra/railway/api.json). Tests pass
# host="127.0.0.1" explicitly.
_DEFAULT_HOST = "0.0.0.0"  # noqa: S104  # nosec B104


class Liveness:
    """Thread-safe last-progress timestamp shared by the loop and the server.

    The consumer loop never sees this class; the entrypoint wraps
    :meth:`touch` in the ``should_continue`` callback it already passes to
    ``run_worker``, so one existing hook carries both "keep going?" and
    "you are alive".
    """

    def __init__(
        self,
        *,
        queue: str = "unknown",
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._monotonic = monotonic
        self._queue = queue
        self._lock = threading.Lock()
        self._last = monotonic()

    @property
    def queue(self) -> str:
        return self._queue

    def touch(self) -> None:
        """Record that the loop made progress just now."""
        with self._lock:
            self._last = self._monotonic()

    def age_seconds(self) -> float:
        """Seconds since the last :meth:`touch` (or since construction)."""
        with self._lock:
            last = self._last
        return max(0.0, self._monotonic() - last)

    def snapshot(self, *, max_age_seconds: float) -> tuple[int, dict[str, Any]]:
        """Return the ``(http_status, body)`` pair for the current state."""
        age = self.age_seconds()
        healthy = age <= max_age_seconds
        return (
            200 if healthy else 503,
            {
                "status": "ok" if healthy else "stale",
                "last_heartbeat_age_seconds": round(age, 3),
                "queue": self._queue,
            },
        )


def _make_handler(liveness: Liveness, max_age_seconds: float) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        # Keep the JSON log format clean: the default handler writes
        # unstructured lines straight to stderr for every probe.
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            log.debug("health request: " + format, *args)

        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
            if self.path.split("?", 1)[0] != "/health":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status, body = liveness.snapshot(max_age_seconds=max_age_seconds)
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return HealthHandler


def serve_health(
    liveness: Liveness,
    *,
    port: int,
    host: str = _DEFAULT_HOST,
    max_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> ThreadingHTTPServer:
    """Bind the health server without serving; returns the bound server.

    Split from :func:`start_health_server` so tests can bind port 0 and read
    the ephemeral port off ``server.server_address`` before any request.
    """
    return ThreadingHTTPServer((host, port), _make_handler(liveness, max_age_seconds))


def start_health_server(
    liveness: Liveness,
    *,
    port: int,
    host: str = _DEFAULT_HOST,
    max_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Bind and serve ``GET /health`` on a daemon thread.

    Daemon so the endpoint can never keep a stopped worker alive: process
    exit is decided by the consumer loop, never by the probe server.
    """
    server = serve_health(liveness, port=port, host=host, max_age_seconds=max_age_seconds)
    thread = threading.Thread(target=server.serve_forever, name="worker-health", daemon=True)
    thread.start()
    log.info("worker health endpoint listening on %s:%d", host, server.server_address[1])
    return server, thread
