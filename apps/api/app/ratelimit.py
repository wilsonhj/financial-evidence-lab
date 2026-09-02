"""In-process per-organization token-bucket rate limiting (#191).

Scope, deliberately: this limiter lives in one API process's memory and is
keyed by ``(org_id, route_name)``. It bounds what a single tenant can do to a
single instance — enough to stop one workspace's retry loop from monopolising
the connection pool and the provider budget — and nothing more. A **shared**
limiter (Redis token buckets across every replica) is *deferred* per ADR-0002,
which keeps Redis out of the MVP stack; until that ADR is revisited the
effective global limit is ``replicas x FEL_RATE_LIMIT_QPS``, and this module is
the seam a shared backend plugs into (``RateLimiter.check`` is the whole
interface).

Configuration (env, read once per limiter):

* ``FEL_RATE_LIMIT_QPS``   — sustained refill rate per key. ``0`` disables.
* ``FEL_RATE_LIMIT_BURST`` — bucket capacity, i.e. the largest instantaneous
  burst a key may spend before it is shaped down to the sustained rate.

Defaults (5 qps, burst 20) are generous on purpose: the limiter exists to stop
runaway clients, not to shape normal interactive use.

The clock is injectable so tests advance time deterministically instead of
sleeping.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.auth import TenantContext
from app.config import settings
from app.dependencies import get_tenant_context
from app.errors import api_error

# Buckets for keys that have been idle for longer than this are dropped on the
# next sweep, so an unbounded key space (many orgs x routes) cannot grow the
# limiter without bound.
_IDLE_EVICTION_SECONDS = 3600.0


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    """A thread-safe token bucket per key.

    ``check`` is the entire interface: it either consumes one token and returns
    ``None``, or returns the number of whole seconds the caller should wait.
    """

    def __init__(
        self,
        *,
        qps: float,
        burst: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if qps < 0 or burst < 0:
            raise ValueError("rate limit qps and burst must be non-negative")
        self._qps = qps
        self._burst = max(burst, 1.0) if qps > 0 else burst
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    @property
    def enabled(self) -> bool:
        return self._qps > 0

    def check(self, org_id: str, route: str) -> int | None:
        """Consume one token for ``(org_id, route)``.

        Returns ``None`` when the request is allowed, otherwise the Retry-After
        value in seconds (always >= 1, so a client never busy-loops on 0).
        """
        if not self.enabled:
            return None
        key = (org_id, route)
        now = self._clock()
        with self._lock:
            self._evict_idle(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self._burst, updated_at=now)
                self._buckets[key] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._qps)
            bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return None
            deficit = 1.0 - bucket.tokens
        # Round up: a fractional wait is reported as one whole second so the
        # client's next attempt is actually admissible.
        return max(1, math.ceil(deficit / self._qps))

    def _evict_idle(self, now: float) -> None:
        if len(self._buckets) < 1024:
            return
        stale = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.updated_at > _IDLE_EVICTION_SECONDS
        ]
        for key in stale:
            del self._buckets[key]


_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def get_limiter() -> RateLimiter:
    """The process-wide limiter, built from the environment on first use."""
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            cfg = settings()
            _limiter = RateLimiter(qps=cfg.rate_limit_qps, burst=cfg.rate_limit_burst)
        return _limiter


def set_limiter(limiter: RateLimiter | None) -> None:
    """Install (or, with ``None``, discard) the process-wide limiter.

    Tests use this to inject a limiter with a fake clock; passing ``None``
    restores lazy construction from the environment.
    """
    global _limiter
    with _limiter_lock:
        _limiter = limiter


def rate_limit(route: str) -> Callable[[TenantContext], None]:
    """Build a FastAPI dependency limiting ``route`` per calling organization.

    The tenant context is resolved by the same cached dependency the endpoint
    itself uses, so the limiter costs no extra database work — and an
    unauthenticated caller is rejected by authentication before it can consume
    another tenant's budget.
    """

    def dependency(
        ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    ) -> None:
        retry_after = get_limiter().check(ctx.org_id, route)
        if retry_after is not None:
            raise api_error(
                429,
                "RATE_LIMITED",
                "Too many requests for this organization; retry after the indicated delay.",
                {"route": route, "retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
