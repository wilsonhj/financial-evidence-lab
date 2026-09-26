"""Shared throttled + retrying HTTP client plumbing for ingestion adapters.

SEC, FRED, and Alpha Vantage clients all need the same behavior: a
client-side minimum request interval (fair access / rate limits), bounded
retry with exponential backoff on transient failures (429/5xx and transport
errors), and a hard error on client errors. ``transport``, ``sleep``, and
``monotonic`` are injectable so unit tests run against recorded fixtures
with a fake clock and no real waiting; nothing here ever hits the network
in CI.

Retrieval is also bounded, because some request URLs (e.g. the
``sec_filing_fetch`` job payload) are not built by the adapter itself:

- ``allowed_hosts`` pins every hop, including each redirect hop *before* it
  is sent, to HTTPS on an exact host set. A redirect off the allowlist is
  refused, not followed and then checked.
- A 3xx response when redirects are not followed is an error, never a
  successful response whose body a caller then tries to parse.
- The decoded body is capped at ``max_response_bytes``. The cap counts
  decompressed bytes, so a small gzip body cannot expand past it.
- Each attempt has a total ``deadline_seconds``; httpx's own timeout is
  per socket operation, so a slow-drip body could otherwise run unbounded.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping

import httpx

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_DEADLINE_SECONDS = 300.0
# Describe the stored body, not the wire encoding it was decoded from.
_WIRE_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def base_url_host(base_url: str) -> frozenset[str]:
    """The one-host allowlist for an adapter bound to an HTTPS ``base_url``."""
    parsed = httpx.URL(base_url)
    if parsed.scheme != "https" or not parsed.host:
        raise ValueError("base_url must be an absolute https:// URL")
    return frozenset({parsed.host.lower()})


class HttpRequestError(Exception):
    """A request failed after exhausting retries or with a client error."""


class _DeadlineExceeded(Exception):
    """One attempt ran past its total deadline (retryable)."""


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
        allowed_hosts: Iterable[str] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(max_response_bytes) is not int or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        if not deadline_seconds > 0:
            raise ValueError("deadline_seconds must be positive")
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._max_response_bytes = max_response_bytes
        self._deadline_seconds = deadline_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at = float("-inf")
        self._allowed_hosts = (
            None if allowed_hosts is None else frozenset(host.lower() for host in allowed_hosts)
        )
        if self._allowed_hosts is not None and not self._allowed_hosts:
            raise ValueError("allowed_hosts must name at least one host when set")
        self._client = httpx.Client(
            headers=dict(headers) if headers else None,
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
            event_hooks={"request": [self._check_destination]},
        )

    def close(self) -> None:
        self._client.close()

    def _check_destination(self, request: httpx.Request) -> None:
        """Refuse any hop (initial or redirect) outside the HTTPS allowlist."""
        if self._allowed_hosts is None:
            return
        host = (request.url.host or "").lower()
        if request.url.scheme != "https" or host not in self._allowed_hosts:
            # Name only the host: query strings can carry API keys.
            raise HttpRequestError(
                f"refusing request to {request.url.scheme}://{host}: "
                "destination is outside this client's HTTPS host allowlist"
            )

    def _throttle(self) -> None:
        wait = self._last_request_at + self._min_interval - self._monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _read_bounded(self, response: httpx.Response, url: str, started: float) -> bytes:
        declared = response.headers.get("content-length")
        if (
            "content-encoding" not in response.headers
            and declared is not None
            and declared.isdigit()
            and int(declared) > self._max_response_bytes
        ):
            raise HttpRequestError(
                f"GET {url} declared {declared} bytes, over the "
                f"{self._max_response_bytes}-byte response limit"
            )
        body = bytearray()
        for chunk in response.iter_bytes():
            if self._monotonic() - started > self._deadline_seconds:
                raise _DeadlineExceeded
            if len(body) + len(chunk) > self._max_response_bytes:
                raise HttpRequestError(
                    f"GET {url} exceeded the {self._max_response_bytes}-byte response limit"
                )
            body.extend(chunk)
        return bytes(body)

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> httpx.Response:
        """GET with throttle + retry; raises :class:`HttpRequestError`.

        The returned response is fully read and carries the decoded body.
        """
        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                self._sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            self._throttle()
            started = self._monotonic()
            try:
                with self._client.stream("GET", url, params=params) as response:
                    status = response.status_code
                    if status in RETRYABLE_STATUS:
                        last_error = f"retryable status {status}"
                        continue
                    if status >= 400:
                        raise HttpRequestError(f"GET {url} failed with status {status}")
                    if response.is_redirect:
                        raise HttpRequestError(
                            f"GET {url} returned redirect status {status}; "
                            "redirects are not followed by this client"
                        )
                    body = self._read_bounded(response, url, started)
                    return httpx.Response(
                        status,
                        headers=[
                            (name, value)
                            for name, value in response.headers.multi_items()
                            if name.lower() not in _WIRE_HEADERS
                        ],
                        content=body,
                        request=response.request,
                    )
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc}"
                continue
            except _DeadlineExceeded:
                last_error = f"response exceeded the {self._deadline_seconds}s deadline"
                continue
        raise HttpRequestError(
            f"GET {url} failed after {self._max_retries + 1} attempts ({last_error})"
        )
