"""Live SEC EDGAR client (T0101, FR-ING-001/006).

Implements the frozen ``fel_providers.interfaces.SecClient`` protocol against
the public data.sec.gov submissions API with SEC fair-access controls: a
compliant identifying User-Agent, a hard client-side rate limit (default
2 requests/second), and bounded retry with exponential backoff on transient
failures — all via the shared :mod:`fel_workers.http` helper. Never
exercised live in CI — unit tests inject an ``httpx.MockTransport`` over
recorded (synthetic) fixture JSON, and the committed mocks remain the
default binding for all pipelines.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

import httpx

from fel_workers.http import HttpRequestError, ThrottledRetryingClient

SEC_USER_AGENT = "financial-evidence-lab research (sordidsunday@icloud.com)"
SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"


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
        self._client = ThrottledRetryingClient(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
            timeout_seconds=timeout_seconds,
            min_interval_seconds=min_interval_seconds,
            max_retries=max_retries,
            follow_redirects=True,
            sleep=sleep,
            monotonic=monotonic,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str) -> httpx.Response:
        try:
            return self._client.get(url)
        except HttpRequestError as exc:
            raise SecFetchError(str(exc)) from exc

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
