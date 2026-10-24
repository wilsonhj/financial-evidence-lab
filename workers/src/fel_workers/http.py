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
- Redirects are followed here, hop by hop, rather than by httpx, which would
  read each redirect body in full outside these bounds. A redirect body is
  never read, at most ``MAX_REDIRECTS`` hops are followed, and every hop is
  charged to the attempt deadline.
- A 3xx response when redirects are not followed is an error, never a
  successful response whose body a caller then tries to parse.
- The decoded body is capped at ``max_response_bytes``. The cap counts
  decompressed bytes, so a small gzip body cannot expand past it.
- Each attempt, redirect hops included, has a total ``deadline_seconds``;
  httpx's own timeout is per socket operation, so a slow-drip body could
  otherwise run unbounded.

Every successful GET can also yield a :class:`RetrievalReceipt` (ADR-0029):
which URL was asked for and answered, when, with what status and content
type, and the SHA-256 of the exact decoded bytes the caller parses. Query
parameters named in ``secret_query_params`` (API keys) are redacted in the
receipt, so it can be stored and shown next to the numbers it vouches for.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_DEADLINE_SECONDS = 300.0
MAX_REDIRECTS = 20  # httpx's own default
# Describe the stored body, not the wire encoding it was decoded from.
_WIRE_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})
REDACTED = "REDACTED"


@dataclass(frozen=True)
class RetrievalReceipt:
    """Provenance for one successful GET (ADR-0029).

    ``content_sha256`` hashes the decoded body exactly as the adapter parsed
    it, in the repository-wide ``sha256:<hex>`` format, so a stored copy of
    those bytes can be checked against it. ``retrieved_at`` is the UTC
    instant the body finished reading. URLs carry the full query with secret
    parameter values replaced by ``REDACTED``; ``final_url`` differs from
    ``source_url`` only when a followed redirect moved the request.
    """

    source_url: str
    final_url: str
    retrieved_at: datetime
    status_code: int
    content_type: str | None
    byte_length: int
    content_sha256: str
    attempts: int


def redact_url(url: httpx.URL, secret_params: frozenset[str]) -> str:
    """``url`` with the values of ``secret_params`` (case-insensitive) redacted."""
    if not secret_params or not url.query:
        return str(url)
    params = [
        (name, REDACTED if name.lower() in secret_params else value)
        for name, value in url.params.multi_items()
    ]
    return str(url.copy_with(params=params))


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
        secret_query_params: Iterable[str] = (),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(max_response_bytes) is not int or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        if not deadline_seconds > 0:
            raise ValueError("deadline_seconds must be positive")
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._follow_redirects = follow_redirects
        self._max_response_bytes = max_response_bytes
        self._deadline_seconds = deadline_seconds
        self._secret_query_params = frozenset(name.lower() for name in secret_query_params)
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
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

    def _open(self, url: str, params: Mapping[str, str] | None, started: float) -> httpx.Response:
        """Send the GET, following redirects if enabled; the result is unread.

        The caller must close the returned response.
        """
        request = self._client.build_request("GET", url, params=params)
        for _ in range(MAX_REDIRECTS + 1):
            response = self._client.send(request, stream=True)
            next_request = response.next_request
            if not self._follow_redirects or next_request is None:
                return response
            response.close()  # the redirect body is never read
            if self._monotonic() - started > self._deadline_seconds:
                raise _DeadlineExceeded
            request = next_request
        raise HttpRequestError(f"GET {url} was redirected more than {MAX_REDIRECTS} times")

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
        response, _receipt = self.get_with_receipt(url, params=params)
        return response

    def get_with_receipt(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> tuple[httpx.Response, RetrievalReceipt]:
        """:meth:`get`, plus the :class:`RetrievalReceipt` for its body."""
        last_error = "unknown error"
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                self._sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            self._throttle()
            started = self._monotonic()
            try:
                response = self._open(url, params, started)
                try:
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
                    retrieved_at = self._now()
                    if retrieved_at.tzinfo is None:
                        raise ValueError("the receipt clock must return timezone-aware times")
                    receipt = RetrievalReceipt(
                        source_url=redact_url(
                            self._client.build_request("GET", url, params=params).url,
                            self._secret_query_params,
                        ),
                        final_url=redact_url(response.request.url, self._secret_query_params),
                        retrieved_at=retrieved_at.astimezone(UTC),
                        status_code=status,
                        content_type=response.headers.get("content-type"),
                        byte_length=len(body),
                        content_sha256=f"sha256:{hashlib.sha256(body).hexdigest()}",
                        attempts=attempt + 1,
                    )
                    decoded = httpx.Response(
                        status,
                        headers=[
                            (name, value)
                            for name, value in response.headers.multi_items()
                            if name.lower() not in _WIRE_HEADERS
                        ],
                        content=body,
                        request=response.request,
                    )
                    return decoded, receipt
                finally:
                    response.close()
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc}"
                continue
            except _DeadlineExceeded:
                last_error = f"response exceeded the {self._deadline_seconds}s deadline"
                continue
        raise HttpRequestError(
            f"GET {url} failed after {self._max_retries + 1} attempts ({last_error})"
        )
