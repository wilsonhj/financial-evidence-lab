"""Live SEC EDGAR client (T0101, FR-ING-001/006).

Implements the frozen ``fel_providers.interfaces.SecClient`` protocol against
the public data.sec.gov submissions API with SEC fair-access controls: a
compliant identifying User-Agent, a hard client-side rate limit (default
2 requests/second), and bounded retry with exponential backoff on transient
failures. Never exercised live in CI — unit tests inject an
``httpx.MockTransport`` over recorded (synthetic) fixture JSON, and the
committed mocks remain the default binding for all pipelines.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

import httpx

SEC_USER_AGENT = "financial-evidence-lab research (sordidsunday@icloud.com)"
SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SecFetchError(Exception):
    """A SEC request failed after exhausting retries or with a client error."""


def normalize_cik(cik: str) -> str:
    """Return the zero-padded 10-digit CIK the submissions API expects."""
    digits = cik.strip().lstrip("CIK").strip()
    if not digits.isdigit():
        raise SecFetchError(f"invalid CIK {cik!r}: expected digits")
    return digits.zfill(10)


class LiveSecClient:
    """SecClient over EDGAR with fair-access rate limiting and retry.

    ``transport``, ``sleep``, and ``monotonic`` are injectable so unit tests
    run against recorded fixtures with a fake clock and no real waiting.
    """

    def __init__(
        self,
        *,
        user_agent: str = SEC_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
        min_interval_seconds: float = 0.5,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at = float("-inf")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        wait = self._last_request_at + self._min_interval - self._monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _get(self, url: str) -> httpx.Response:
        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                self._sleep(0.5 * 2 ** (attempt - 1))
            self._throttle()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc}"
                continue
            if response.status_code in _RETRYABLE_STATUS:
                last_error = f"retryable status {response.status_code}"
                continue
            if response.status_code >= 400:
                raise SecFetchError(f"GET {url} failed with status {response.status_code}")
            return response
        raise SecFetchError(
            f"GET {url} failed after {self._max_retries + 1} attempts ({last_error})"
        )

    def submissions(self, cik: str) -> dict[str, object]:
        """Fetch the issuer's submissions index (SecClient protocol)."""
        url = f"{SUBMISSIONS_BASE_URL}/CIK{normalize_cik(cik)}.json"
        payload = self._get(url).json()
        if not isinstance(payload, dict):
            raise SecFetchError(f"GET {url} returned a non-object JSON payload")
        return cast(dict[str, object], payload)

    def fetch_document(self, url: str) -> bytes:
        """Fetch raw filing bytes (SecClient protocol)."""
        return self._get(url).content
