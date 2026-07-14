"""T0101: LiveSecClient fair-access behavior over recorded fixtures.

Every test injects an httpx.MockTransport — no request ever leaves the
process, and CI never touches live SEC hosts.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest

from fel_workers.ingestion.sec_client import (
    SEC_USER_AGENT,
    LiveSecClient,
    SecFetchError,
    normalize_cik,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


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


def _client(handler, clock: FakeClock, **kwargs) -> LiveSecClient:
    return LiveSecClient(
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kwargs,
    )


def test_normalize_cik() -> None:
    assert normalize_cik("9999999") == "0009999999"
    assert normalize_cik("CIK0009999999") == "0009999999"
    with pytest.raises(SecFetchError):
        normalize_cik("not-a-cik")


def test_submissions_sends_compliant_user_agent_and_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=fixture_bytes("sec_submissions_synthetic.json"))

    clock = FakeClock()
    payload = _client(handler, clock).submissions("9999999")
    assert seen[0].headers["User-Agent"] == SEC_USER_AGENT
    assert "sordidsunday@icloud.com" in SEC_USER_AGENT
    assert str(seen[0].url) == "https://data.sec.gov/submissions/CIK0009999999.json"
    assert payload["cik"] == "9999999"
    recent = payload["filings"]["recent"]  # type: ignore[index]
    assert recent["accessionNumber"][0] == "0009999999-26-000010"


def test_rate_limit_enforces_min_interval() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.5)
    client.fetch_document("https://data.sec.gov/a")
    client.fetch_document("https://data.sec.gov/b")
    client.fetch_document("https://data.sec.gov/c")
    # Requests are instantaneous under the fake clock, so every follow-up
    # request must wait the full 0.5s fair-access interval.
    assert clock.sleeps == [0.5, 0.5]


def test_retries_with_backoff_then_succeeds() -> None:
    statuses = iter([503, 429])

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return httpx.Response(next(statuses))
        except StopIteration:
            return httpx.Response(200, content=b"payload")

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0)
    assert client.fetch_document("https://data.sec.gov/doc") == b"payload"
    # Two failures -> two exponential backoff sleeps (0.5, then 1.0).
    assert clock.sleeps == [0.5, 1.0]


def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0, max_retries=2)
    with pytest.raises(SecFetchError, match="after 3 attempts"):
        client.fetch_document("https://data.sec.gov/doc")


def test_client_error_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    clock = FakeClock()
    client = _client(handler, clock, min_interval_seconds=0.0)
    with pytest.raises(SecFetchError, match="status 404"):
        client.fetch_document("https://data.sec.gov/missing")
    assert len(calls) == 1


def test_non_object_submissions_payload_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps([1, 2]).encode())

    clock = FakeClock()
    with pytest.raises(SecFetchError, match="non-object"):
        _client(handler, clock).submissions("9999999")
