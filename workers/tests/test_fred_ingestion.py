"""T0107: vintage-aware FRED ingestion through the FredClient protocol."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from fel_providers.mocks import MockFredClient
from fel_workers.ingestion.fred import (
    FredIngestionError,
    LiveFredClient,
    ingest_fred_vintage,
    vintage_cutoff_date,
)


def test_vintage_as_of_is_respected() -> None:
    """Different cutoffs must yield different vintages (mock is anchored to
    the as_of month), and equal cutoffs identical ones — deterministically."""
    client = MockFredClient()
    march = ingest_fred_vintage(client, "CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))
    july = ingest_fred_vintage(client, "CPIAUCSL", as_of=datetime(2026, 7, 15, tzinfo=UTC))
    assert march != july, "as_of must select the vintage"
    assert {o.observed_on for o in march} != {o.observed_on for o in july}
    again = ingest_fred_vintage(client, "CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))
    assert march == again
    assert all(o.as_of == datetime(2026, 3, 15, tzinfo=UTC) for o in march)
    assert all(isinstance(o.value, Decimal) for o in march)
    days = [o.observed_on for o in march]
    assert days == sorted(days)


def test_naive_as_of_is_rejected() -> None:
    with pytest.raises(FredIngestionError, match="timezone-aware"):
        ingest_fred_vintage(MockFredClient(), "CPIAUCSL", as_of=datetime(2026, 3, 15))


def test_live_client_pins_realtime_window_to_as_of() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-01-01", "value": "310.5"},
                    {"date": "2026-02-01", "value": "."},
                    {"date": "2026-03-01", "value": "311.2"},
                ]
            },
        )

    client = LiveFredClient("test-key-not-a-secret", transport=httpx.MockTransport(handler))
    points = client.series_vintage("CPIAUCSL", as_of=datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    params = dict(seen[0].url.params)
    # Fail-closed day policy (finding 9): the realtime window is the last
    # WHOLE UTC day before the cutoff, never the cutoff's own (partial) day.
    assert params["realtime_start"] == "2026-03-14"
    assert params["realtime_end"] == "2026-03-14"
    assert params["series_id"] == "CPIAUCSL"
    # Missing observations (".") are skipped, values are Decimal.
    assert points == [
        (date(2026, 1, 1), Decimal("310.5")),
        (date(2026, 3, 1), Decimal("311.2")),
    ]


def test_vintage_cutoff_date_is_utc_normalized_and_never_looks_ahead() -> None:
    """Finding 9: the ALFRED vintage day is derived from the UTC instant, so
    tz-shifted spellings of the SAME instant yield the SAME vintage day, and
    the chosen day always ends at or before the cutoff (no lookahead)."""
    utc_spelling = datetime(2026, 3, 14, 20, 0, tzinfo=UTC)
    shifted_spelling = datetime(2026, 3, 15, 1, 0, tzinfo=timezone(timedelta(hours=5)))
    assert utc_spelling == shifted_spelling
    assert vintage_cutoff_date(utc_spelling) == vintage_cutoff_date(shifted_spelling)
    # A wall-clock date policy would have used 2026-03-14 for one spelling
    # and 2026-03-15 for the other; both must resolve to 2026-03-13 (the
    # last whole UTC day strictly before the cutoff instant).
    assert vintage_cutoff_date(utc_spelling) == date(2026, 3, 13)
    # No-lookahead invariant: the end of the vintage day never exceeds as_of.
    for hour in (0, 1, 12, 23):
        as_of = datetime(2026, 3, 15, hour, tzinfo=UTC)
        cutoff = vintage_cutoff_date(as_of)
        day_end = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=UTC) + timedelta(days=1)
        assert day_end <= as_of
    with pytest.raises(FredIngestionError, match="timezone-aware"):
        vintage_cutoff_date(datetime(2026, 3, 15))


def test_live_client_tz_shifted_as_of_requests_identical_vintage() -> None:
    """Finding 9: the same instant expressed in different timezones must hit
    ALFRED with identical realtime parameters."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"observations": []})

    client = LiveFredClient(
        "test-key-not-a-secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda seconds: None,
    )
    client.series_vintage("CPIAUCSL", as_of=datetime(2026, 3, 14, 20, 0, tzinfo=UTC))
    client.series_vintage(
        "CPIAUCSL",
        as_of=datetime(2026, 3, 15, 1, 0, tzinfo=timezone(timedelta(hours=5))),
    )
    first, second = (dict(request.url.params) for request in seen)
    assert first["realtime_start"] == second["realtime_start"] == "2026-03-13"
    assert first["realtime_end"] == second["realtime_end"] == "2026-03-13"


def test_live_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_FRED_API_KEY", raising=False)
    with pytest.raises(FredIngestionError, match="FEL_FRED_API_KEY"):
        LiveFredClient()


def test_live_client_rejects_malformed_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"unexpected": True}).encode())

    client = LiveFredClient("test-key-not-a-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(FredIngestionError, match="observations"):
        client.series_vintage("CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))


def test_live_client_surfaces_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = LiveFredClient("test-key-not-a-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(FredIngestionError, match="status 500"):
        client.series_vintage("CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))
