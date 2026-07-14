"""Shared throttled + retrying HTTP client plumbing for ingestion adapters.

SEC, FRED, and Alpha Vantage clients all need the same behavior: a
client-side minimum request interval (fair access / rate limits), bounded
retry with exponential backoff on transient failures (429/5xx and transport
errors), and a hard error on client errors. ``transport``, ``sleep``, and
``monotonic`` are injectable so unit tests run against recorded fixtures
with a fake clock and no real waiting; nothing here ever hits the network
in CI.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

import httpx

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5


class HttpRequestError(Exception):
    """A request failed after exhausting retries or with a client error."""


class ThrottledRetryingClient:
    """httpx wrapper with min-interval throttling and bounded backoff retry."""

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
        min_interval_seconds: float = 0.0,
        max_retries: int = 3,
        follow_redirects: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at = float("-inf")
        self._client = httpx.Client(
            headers=dict(headers) if headers else None,
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
        )

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        wait = self._last_request_at + self._min_interval - self._monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._monotonic()

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> httpx.Response:
        """GET with throttle + retry; raises :class:`HttpRequestError`."""
        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                self._sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            self._throttle()
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc}"
                continue
            if response.status_code in RETRYABLE_STATUS:
                last_error = f"retryable status {response.status_code}"
                continue
            if response.status_code >= 400:
                raise HttpRequestError(f"GET {url} failed with status {response.status_code}")
            return response
        raise HttpRequestError(
            f"GET {url} failed after {self._max_retries + 1} attempts ({last_error})"
        )
