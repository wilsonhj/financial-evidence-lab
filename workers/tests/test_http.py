"""Finding 14: shared throttled/retrying HTTP helper used by the SEC, FRED,
and Alpha Vantage adapters. Transport, sleep, and clock are injected — no
request ever leaves the process."""

from __future__ import annotations

import httpx
import pytest

from fel_workers.http import HttpRequestError, ThrottledRetryingClient
from fel_workers.ingestion.fred import LiveFredClient
from fel_workers.ingestion.market import AlphaVantageMarketDataProvider
from fel_workers.ingestion.sec_client import LiveSecClient


class FakeClock:
    """Deterministic monotonic clock advanced by recorded sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(handler, clock: FakeClock, **kwargs) -> ThrottledRetryingClient:
    return ThrottledRetryingClient(
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kwargs,
    )


def test_min_interval_throttles_consecutive_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.5)
    for _ in range(3):
        client.get("https://example.invalid/x")
    assert clock.sleeps == [0.5, 0.5]


def test_retryable_statuses_back_off_exponentially_then_succeed() -> None:
    statuses = iter([503, 429, 502])

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return httpx.Response(next(statuses))
        except StopIteration:
            return httpx.Response(200, content=b"payload")

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0)
    response = client.get("https://example.invalid/x")
    assert response.content == b"payload"
    assert clock.sleeps == [0.5, 1.0, 2.0]


def test_transport_errors_are_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=b"recovered")

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0)
    assert client.get("https://example.invalid/x").content == b"recovered"


def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0, max_retries=2)
    with pytest.raises(HttpRequestError, match="after 3 attempts"):
        client.get("https://example.invalid/x")


def test_client_errors_fail_immediately_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0)
    with pytest.raises(HttpRequestError, match="status 404"):
        client.get("https://example.invalid/x")
    assert len(calls) == 1


def test_headers_and_params_are_forwarded() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    clock = FakeClock()
    client = ThrottledRetryingClient(
        headers={"User-Agent": "fel-test"},
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    client.get("https://example.invalid/x", params={"a": "1"})
    assert seen[0].headers["User-Agent"] == "fel-test"
    assert dict(seen[0].url.params) == {"a": "1"}


def test_all_three_adapters_share_the_helper() -> None:
    """SEC + FRED + Alpha Vantage all route through ThrottledRetryingClient
    (one place to audit throttling/retry/fair-access behavior)."""
    handler = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    sec = LiveSecClient(transport=handler)
    fred = LiveFredClient("test-key-not-a-secret", transport=handler)
    market = AlphaVantageMarketDataProvider("test-key-not-a-secret", transport=handler)
    for adapter in (sec, fred, market):
        assert isinstance(adapter._client, ThrottledRetryingClient)  # noqa: SLF001
        adapter.close()
