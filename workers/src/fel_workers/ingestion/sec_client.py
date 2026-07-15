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

import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import cast

import httpx

from fel_workers.http import HttpRequestError, ThrottledRetryingClient

SEC_USER_AGENT = "financial-evidence-lab research (sordidsunday@icloud.com)"
SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
COMPANY_FACTS_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"


class SecFetchError(Exception):
    """A SEC request failed after exhausting retries or with a client error."""


def normalize_cik(cik: str) -> str:
    """Return the zero-padded 10-digit CIK the submissions API expects."""
    digits = cik.strip().lstrip("CIK").strip()
    if not digits.isdigit():
        raise SecFetchError(f"invalid CIK {cik!r}: expected digits")
    return digits.zfill(10)


def company_facts_url(cik: str) -> str:
    """Canonical data.sec.gov companyfacts URL for an issuer (FR-ING-001)."""
    return f"{COMPANY_FACTS_BASE_URL}/CIK{normalize_cik(cik)}.json"


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

    def company_facts(self, cik: str) -> dict[str, object]:
        """Fetch the issuer's XBRL companyfacts aggregate (issue #83).

        Same shared throttled/retrying transport and fair-access discipline
        as every other SEC request (workers-local CompanyFactsSecClient
        capability; the frozen SecClient protocol is untouched).

        Decodes with ``parse_float=Decimal`` so stored corpus bytes (via
        ``canonical_company_facts_bytes``) preserve numeric fidelity —
        ``response.json()`` IEEE-754 decoding is deliberately avoided.
        """
        url = company_facts_url(cik)
        raw = self._get(url).content
        try:
            payload = json.loads(raw.decode("utf-8"), parse_float=Decimal)
        except UnicodeDecodeError as exc:
            raise SecFetchError(f"GET {url} returned non-UTF-8 body") from exc
        except json.JSONDecodeError as exc:
            raise SecFetchError(
                f"GET {url} returned invalid JSON (line {exc.lineno} "
                f"column {exc.colno}: {exc.msg})"
            ) from exc
        if not isinstance(payload, dict):
            raise SecFetchError(f"GET {url} returned a non-object JSON payload")
        return cast(dict[str, object], payload)

    def fetch_document(self, url: str) -> bytes:
        """Fetch raw filing bytes (SecClient protocol)."""
        return self._get(url).content
