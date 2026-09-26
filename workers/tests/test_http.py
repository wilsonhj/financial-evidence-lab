"""Finding 14: shared throttled/retrying HTTP helper used by the SEC, FRED,
and Alpha Vantage adapters. Transport, sleep, and clock are injected — no
request ever leaves the process."""

from __future__ import annotations

import gzip

import httpx
import pytest

from fel_workers.http import HttpRequestError, ThrottledRetryingClient, base_url_host
from fel_workers.ingestion.fred import LiveFredClient
from fel_workers.ingestion.market import AlphaVantageMarketDataProvider
from fel_workers.ingestion.sec_client import LiveSecClient, SecFetchError


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


# --- Bounded retrieval: allowlist, redirects, size cap, deadline ----------


def test_allowlist_refuses_off_list_host_before_sending() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    client = _client(handler, FakeClock(), allowed_hosts={"data.sec.gov"})
    with pytest.raises(HttpRequestError, match="outside this client's HTTPS host allowlist"):
        client.get("https://169.254.169.254/latest/meta-data/")
    assert calls == []


def test_allowlist_refuses_plain_http_on_an_allowed_host() -> None:
    client = _client(lambda r: httpx.Response(200), FakeClock(), allowed_hosts={"data.sec.gov"})
    with pytest.raises(HttpRequestError, match="allowlist"):
        client.get("http://data.sec.gov/x")


def test_allowlist_checks_each_redirect_hop_before_following_it() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.host))
        if request.url.host == "www.sec.gov":
            return httpx.Response(302, headers={"Location": "https://internal.invalid/secret"})
        return httpx.Response(200, content=b"leaked")

    client = _client(
        handler,
        FakeClock(),
        allowed_hosts={"www.sec.gov"},
        follow_redirects=True,
    )
    with pytest.raises(HttpRequestError, match="internal.invalid"):
        client.get("https://www.sec.gov/Archives/x.htm")
    assert calls == ["www.sec.gov"]


def test_allowlist_permits_redirect_within_the_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.sec.gov":
            return httpx.Response(301, headers={"Location": "https://data.sec.gov/y"})
        return httpx.Response(200, content=b"ok")

    client = _client(
        handler,
        FakeClock(),
        allowed_hosts={"www.sec.gov", "data.sec.gov"},
        follow_redirects=True,
    )
    assert client.get("https://www.sec.gov/x").content == b"ok"


def test_unfollowed_redirect_is_an_error_not_a_response() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(302, headers={"Location": "https://elsewhere.invalid/"})

    client = _client(handler, FakeClock())
    with pytest.raises(HttpRequestError, match="redirect status 302"):
        client.get("https://example.invalid/x")
    assert len(calls) == 1


def test_declared_oversize_body_is_refused_without_reading() -> None:
    client = _client(
        lambda r: httpx.Response(200, headers={"Content-Length": "11"}, content=b"x" * 11),
        FakeClock(),
        max_response_bytes=10,
    )
    with pytest.raises(HttpRequestError, match="declared 11 bytes"):
        client.get("https://example.invalid/x")


def test_streamed_body_over_limit_is_refused_and_not_retried() -> None:
    calls: list[int] = []

    def chunks():
        yield b"x" * 6
        yield b"x" * 6

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, content=chunks())

    client = _client(handler, FakeClock(), max_response_bytes=10)
    with pytest.raises(HttpRequestError, match="exceeded the 10-byte response limit"):
        client.get("https://example.invalid/x")
    assert len(calls) == 1


def test_size_limit_counts_decompressed_bytes() -> None:
    compressed = gzip.compress(b"0" * 100_000)
    assert len(compressed) < 1_000

    client = _client(
        lambda r: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=compressed),
        FakeClock(),
        max_response_bytes=50_000,
    )
    with pytest.raises(HttpRequestError, match="response limit"):
        client.get("https://example.invalid/x")


def test_decoded_body_is_returned_with_wire_headers_dropped() -> None:
    client = _client(
        lambda r: httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            content=gzip.compress(b'{"a": 1}'),
        ),
        FakeClock(),
    )
    response = client.get("https://example.invalid/x")
    assert response.json() == {"a": 1}
    assert "content-encoding" not in response.headers
    assert response.headers["content-type"] == "application/json"


def test_slow_drip_body_hits_the_attempt_deadline_and_is_retried() -> None:
    clock = FakeClock()
    attempts: list[int] = []

    def slow_chunks():
        for _ in range(5):
            clock.now += 1.0
            yield b"x"

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(200, content=slow_chunks())

    client = _client(handler, clock, deadline_seconds=2.5, max_retries=1)
    with pytest.raises(HttpRequestError, match="2.5s deadline"):
        client.get("https://example.invalid/x")
    assert len(attempts) == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_response_bytes": 0}, "max_response_bytes"),
        ({"max_response_bytes": True}, "max_response_bytes"),
        ({"deadline_seconds": 0}, "deadline_seconds"),
        ({"allowed_hosts": set()}, "allowed_hosts"),
    ],
)
def test_invalid_bounds_are_rejected(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ThrottledRetryingClient(**kwargs)


def test_base_url_host_requires_https() -> None:
    assert base_url_host("https://API.stlouisfed.org/path") == frozenset({"api.stlouisfed.org"})
    with pytest.raises(ValueError, match="https"):
        base_url_host("http://api.stlouisfed.org")


def test_adapters_pin_their_upstream_hosts() -> None:
    blocked = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    sec = LiveSecClient(transport=blocked)
    with pytest.raises(SecFetchError, match="allowlist"):
        sec.fetch_document("https://attacker.invalid/filing.htm")
    assert sec._client._max_response_bytes == 256 * 1024 * 1024  # noqa: SLF001
    fred = LiveFredClient("test-key-not-a-secret", transport=blocked)
    market = AlphaVantageMarketDataProvider("test-key-not-a-secret", transport=blocked)
    assert fred._client._allowed_hosts == {"api.stlouisfed.org"}  # noqa: SLF001
    assert market._client._allowed_hosts == {"www.alphavantage.co"}  # noqa: SLF001
    for adapter in (sec, fred, market):
        adapter.close()
