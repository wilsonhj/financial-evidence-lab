"""T0107: vintage-aware FRED ingestion through the FredClient protocol."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from fel_providers.mocks import MockFredClient
from fel_workers.ingestion.fred import (
    FredIngestionError,
    LiveFredClient,
    ReceiptedFredClient,
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


def test_live_client_wraps_non_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>maintenance</html>")

    client = LiveFredClient("test-key-not-a-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(FredIngestionError, match="not valid JSON"):
        client.series_vintage("CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))


def test_live_client_surfaces_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = LiveFredClient("test-key-not-a-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(FredIngestionError, match="status 500"):
        client.series_vintage("CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))


def test_live_ingest_attaches_a_redacted_receipt_to_every_observation() -> None:
    """ADR-0029: each value carries the receipt of the bytes it came from."""
    body = json.dumps(
        {
            "observations": [
                {"date": "2026-01-01", "value": "310.1"},
                {"date": "2026-02-01", "value": "311.4"},
            ]
        }
    ).encode()
    fetched_at = datetime(2026, 3, 16, 9, 30, tzinfo=UTC)
    client = LiveFredClient(
        "fred-key-not-a-secret",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
        now=lambda: fetched_at,
    )
    observations = ingest_fred_vintage(client, "CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))
    assert isinstance(client, ReceiptedFredClient)
    receipts = {obs.receipt for obs in observations}
    assert len(receipts) == 1
    (receipt,) = receipts
    assert receipt is not None
    assert receipt.content_sha256 == f"sha256:{hashlib.sha256(body).hexdigest()}"
    assert receipt.retrieved_at == fetched_at
    assert "fred-key-not-a-secret" not in repr(receipt)
    assert "api_key=REDACTED" in receipt.source_url
    assert "series_id=CPIAUCSL" in receipt.source_url
    assert "realtime_end=2026-03-14" in receipt.source_url


def test_mock_client_yields_no_receipt() -> None:
    client = MockFredClient()
    assert not isinstance(client, ReceiptedFredClient)
    observations = ingest_fred_vintage(client, "CPIAUCSL", as_of=datetime(2026, 3, 15, tzinfo=UTC))
    assert observations
    assert all(obs.receipt is None for obs in observations)


def test_same_vintage_fetched_twice_is_equal_but_keeps_both_receipts() -> None:
    """Receipts are provenance, not identity: two fetches of one vintage
    compare equal, while each observation keeps its own fetch time."""
    body = json.dumps({"observations": [{"date": "2026-01-01", "value": "310.1"}]}).encode()
    times = iter(
        [datetime(2026, 3, 16, 9, 0, tzinfo=UTC), datetime(2026, 3, 16, 10, 0, tzinfo=UTC)]
    )
    client = LiveFredClient(
        "fred-key-not-a-secret",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
        now=lambda: next(times),
    )
    as_of = datetime(2026, 3, 15, tzinfo=UTC)
    first = ingest_fred_vintage(client, "CPIAUCSL", as_of=as_of)
    second = ingest_fred_vintage(client, "CPIAUCSL", as_of=as_of)
    assert first == second
    assert first[0].receipt is not None and second[0].receipt is not None
    assert first[0].receipt.retrieved_at != second[0].receipt.retrieved_at
    assert first[0].receipt.content_sha256 == second[0].receipt.content_sha256
