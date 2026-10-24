"""T0107: vintage-aware FRED ingestion through the FredClient protocol."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from fel_providers.mocks import MockFredClient
from fel_workers.http import SourceClock
from fel_workers.ingestion.fred import (
    FredIngestionError,
    GapReportingFredClient,
    LiveFredClient,
    MissingObservation,
    ReceiptedFredClient,
    ingest_fred_vintage,
    ingest_fred_vintage_record,
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


# --- Explicit missing values (ADR-0030) -----------------------------------

_GAP_AS_OF = datetime(2026, 3, 15, tzinfo=UTC)


def _gap_client(observations: list[object]) -> LiveFredClient:
    body = json.dumps({"observations": observations}).encode()
    return LiveFredClient(
        "fred-key-not-a-secret",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
    )


def test_record_keeps_alfred_gaps_as_explicit_missing_observations() -> None:
    client = _gap_client(
        [
            {"date": "2026-03-01", "value": "311.2"},
            {"date": "2026-02-01", "value": "."},
            {"date": "2026-01-01", "value": "310.5"},
        ]
    )
    assert isinstance(client, GapReportingFredClient)
    record = ingest_fred_vintage_record(client, "CPIAUCSL", as_of=_GAP_AS_OF)
    assert [(o.observed_on, o.value) for o in record.observations] == [
        (date(2026, 1, 1), Decimal("310.5")),
        (date(2026, 3, 1), Decimal("311.2")),
    ]
    assert record.missing == (
        MissingObservation(series_id="CPIAUCSL", observed_on=date(2026, 2, 1), as_of=_GAP_AS_OF),
    )
    (gap,) = record.missing
    assert gap.receipt is not None
    assert gap.receipt is record.observations[0].receipt
    # The list API is unchanged: same observations, gaps not included.
    assert ingest_fred_vintage(client, "CPIAUCSL", as_of=_GAP_AS_OF) == list(record.observations)


def test_no_gaps_reported_is_distinct_from_gaps_not_knowable() -> None:
    live = ingest_fred_vintage_record(
        _gap_client([{"date": "2026-01-01", "value": "310.5"}]), "CPIAUCSL", as_of=_GAP_AS_OF
    )
    assert live.missing == ()
    mock = ingest_fred_vintage_record(MockFredClient(), "CPIAUCSL", as_of=_GAP_AS_OF)
    assert not isinstance(MockFredClient(), GapReportingFredClient)
    assert mock.observations
    assert mock.missing is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"date": "2026-01-01"}, "malformed"),
        ({"value": "310.5"}, "malformed"),
        ("2026-01-01,310.5", "malformed"),
        ({"date": "2026-01-01", "value": "NaN"}, "not a finite number"),
        ({"date": "2026-01-01", "value": "Infinity"}, "not a finite number"),
        ({"date": "not-a-date", "value": "310.5"}, "unparseable"),
    ],
)
def test_malformed_rows_fail_closed_instead_of_being_skipped(row: object, message: str) -> None:
    client = _gap_client([{"date": "2026-02-01", "value": "311.0"}, row])
    with pytest.raises(FredIngestionError, match=message):
        client.fetch_vintage("CPIAUCSL", as_of=_GAP_AS_OF)
    with pytest.raises(FredIngestionError, match=message):
        client.series_vintage("CPIAUCSL", as_of=_GAP_AS_OF)


@pytest.mark.parametrize("second", ["311.0", "."])
def test_repeated_observation_date_fails_closed(second: str) -> None:
    client = _gap_client(
        [{"date": "2026-01-01", "value": "310.5"}, {"date": "2026-01-01", "value": second}]
    )
    with pytest.raises(FredIngestionError, match="repeats observation date 2026-01-01"):
        client.fetch_vintage("CPIAUCSL", as_of=_GAP_AS_OF)


# --- Named source clocks (ADR-0031) ---------------------------------------


def test_fred_receipt_records_alfred_window_clocks_verbatim() -> None:
    body = json.dumps(
        {
            "realtime_start": "2026-03-14",
            "realtime_end": "2026-03-14",
            "observation_start": "1600-01-01",
            "observation_end": "9999-12-31",
            "observations": [{"date": "2026-01-01", "value": "310.5"}],
        }
    ).encode()
    client = LiveFredClient(
        "fred-key-not-a-secret",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
    )
    record = ingest_fred_vintage_record(client, "CPIAUCSL", as_of=_GAP_AS_OF)
    receipt = record.observations[0].receipt
    assert receipt is not None
    assert receipt.source_clocks == (
        SourceClock(name="realtime_start", value="2026-03-14", path="/realtime_start"),
        SourceClock(name="realtime_end", value="2026-03-14", path="/realtime_end"),
        SourceClock(name="observation_start", value="1600-01-01", path="/observation_start"),
        SourceClock(name="observation_end", value="9999-12-31", path="/observation_end"),
    )


def test_fred_response_without_clocks_reports_none_found() -> None:
    client = _gap_client([{"date": "2026-01-01", "value": "310.5"}])
    fetch = client.fetch_vintage("CPIAUCSL", as_of=_GAP_AS_OF)
    assert fetch.receipt.source_clocks == ()
