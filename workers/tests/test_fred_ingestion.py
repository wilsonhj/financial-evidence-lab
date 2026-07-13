"""T0107: vintage-aware FRED ingestion through the FredClient protocol."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from fel_providers.mocks import MockFredClient
from fel_workers.ingestion.fred import (
    FredIngestionError,
    LiveFredClient,
    ingest_fred_vintage,
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
    assert params["realtime_start"] == "2026-03-15"
    assert params["realtime_end"] == "2026-03-15"
    assert params["series_id"] == "CPIAUCSL"
    # Missing observations (".") are skipped, values are Decimal.
    assert points == [
        (date(2026, 1, 1), Decimal("310.5")),
        (date(2026, 3, 1), Decimal("311.2")),
    ]


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
