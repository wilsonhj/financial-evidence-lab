"""Shared HTTP plumbing for live provider adapters (ADR-0012).

Every live adapter in this package is a thin ``httpx`` client, not a vendor SDK:
the protocols in :mod:`fel_providers.interfaces` are the seam, so an adapter only
has to speak one documented request/response shape. ``transport``, ``sleep`` and
``monotonic`` are injectable exactly as in ``fel_workers.http.ThrottledRetryingClient``
so the contract tests run against recorded fixture transports with a fake clock
and never touch the network.

Failure policy, uniform across adapters:

* ``429`` and ``5xx`` are retried a bounded number of times with exponential
  backoff, honouring a ``Retry-After`` header when the server sends one
  (clamped, so a hostile or mistaken header cannot park a worker for hours).
* Any other ``4xx`` is a hard failure — a bad key, a bad model id or a malformed
  request will not become valid by waiting.
* Transport errors are retried like a ``5xx``.

Security posture: prompts and completions never appear in an exception message
or a log record here. Exceptions carry the status code, the attempt count and
the provider's request id (when it sends one) — nothing derived from the request
body or the response body, both of which contain filing text and model output.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5
# Upper bound on an honoured ``Retry-After``. A provider (or a proxy in front of
# one) can send an arbitrarily large value; a worker that slept on it would look
# like a hang. Anything larger is clamped to this and retried.
MAX_RETRY_AFTER_SECONDS = 60.0

# Header names that identify a request without revealing its content.
_REQUEST_ID_HEADERS = ("request-id", "x-request-id", "openai-request-id")


class ProviderError(RuntimeError):
    """Base class for every live-provider failure."""


class ProviderConfigurationError(ProviderError):
    """The adapter cannot be built: missing key, unknown selection, bad config."""


class ProviderHttpError(ProviderError):
    """The provider call failed (non-retryable status, or retries exhausted)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderProtocolError(ProviderError):
    """The provider answered, but not in its documented shape.

    Raised for a non-JSON body, a response missing the fields the adapter
    contract requires, model output that is not JSON, and model output that does
    not validate against the requested JSON Schema. Fails closed: callers must
    never fall back to parsing free text.
    """


@dataclass(frozen=True)
class LiveHttpConfig:
    """Transport-level configuration for a live adapter.

    Timeouts and retry bounds are configuration, never hard-coded at a call
    site, so an operator can tighten them per deployment.
    """

    timeout_seconds: float = 60.0
    max_retries: int = 3
    min_interval_seconds: float = 0.0
    max_retry_after_seconds: float = MAX_RETRY_AFTER_SECONDS

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ProviderConfigurationError("timeout_seconds must be > 0")
        if self.max_retries < 0:
            raise ProviderConfigurationError("max_retries must be >= 0")


def _request_id(response: httpx.Response) -> str:
    for header in _REQUEST_ID_HEADERS:
        value = response.headers.get(header)
        if value:
            return str(value)
    return "unknown"


def _retry_after_seconds(response: httpx.Response, *, cap: float) -> float | None:
    """Honour an integer/decimal ``Retry-After``; ignore HTTP-date forms."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, cap)


class RetryingJsonClient:
    """POST JSON, retry bounded on 429/5xx, hard-fail other 4xx.

    Deliberately narrow: live adapters need exactly one verb.
    """

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        config: LiveHttpConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config or LiveHttpConfig()
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at = float("-inf")
        self._pending_retry_after = 0.0
        self._client = httpx.Client(
            base_url=base_url,
            headers=dict(headers),
            transport=transport,
            timeout=self._config.timeout_seconds,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        wait = self._last_request_at + self._config.min_interval_seconds - self._monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = self._monotonic()

    def post_json(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """POST ``payload`` and return the decoded JSON object.

        Raises :class:`ProviderHttpError` on a non-retryable status or exhausted
        retries, and :class:`ProviderProtocolError` when the body is not a JSON
        object. Neither message contains request or response content.
        """
        attempts = self._config.max_retries + 1
        last_error = "unknown error"
        last_status: int | None = None
        for attempt in range(attempts):
            delay = _BACKOFF_BASE_SECONDS * 2 ** (attempt - 1) if attempt > 0 else 0.0
            if attempt > 0:
                self._sleep(max(delay, self._pending_retry_after))
            self._pending_retry_after = 0.0
            self._throttle()
            try:
                response = self._client.post(path, json=dict(payload))
            except httpx.TransportError:
                # The exception text can embed the URL only; keep even that out
                # of the message to stay uniformly content-free.
                last_error = "transport error"
                continue
            if response.status_code in RETRYABLE_STATUS:
                last_status = response.status_code
                last_error = f"retryable status {response.status_code}"
                self._pending_retry_after = (
                    _retry_after_seconds(response, cap=self._config.max_retry_after_seconds) or 0.0
                )
                continue
            if response.status_code >= 400:
                raise ProviderHttpError(
                    f"POST {path} failed with status {response.status_code}"
                    f" (request id {_request_id(response)})",
                    status_code=response.status_code,
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderProtocolError(
                    f"POST {path} returned a non-JSON body" f" (request id {_request_id(response)})"
                ) from exc
            if not isinstance(body, dict):
                raise ProviderProtocolError(
                    f"POST {path} returned a JSON {type(body).__name__}, expected an object"
                )
            return body
        raise ProviderHttpError(
            f"POST {path} failed after {attempts} attempts ({last_error})",
            status_code=last_status,
        )


__all__ = [
    "MAX_RETRY_AFTER_SECONDS",
    "RETRYABLE_STATUS",
    "LiveHttpConfig",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderHttpError",
    "ProviderProtocolError",
    "RetryingJsonClient",
]
