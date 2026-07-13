"""T0108/T0109: Alpha Vantage adapter and FOR-005 fail-closed feature
assembly. All transport is mocked; nothing leaves the process."""

from __future__ import annotations

import json
import pathlib
from datetime import date
from decimal import Decimal

import httpx
import pytest

from fel_providers.interfaces import MarketBar
from fel_providers.mocks import MockMarketDataProvider
from fel_workers.ingestion.market import (
    AlphaVantageMarketDataProvider,
    FeatureAssemblyError,
    MarketDataError,
    assemble_forecast_features,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


START, END = date(2026, 7, 1), date(2026, 7, 31)


def _provider(handler) -> AlphaVantageMarketDataProvider:
    return AlphaVantageMarketDataProvider(
        "test-key-not-a-secret", transport=httpx.MockTransport(handler)
    )


def _fixture_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=fixture_bytes("alpha_vantage_daily_adjusted.json"))


def test_daily_adjusted_parses_and_filters_fixture() -> None:
    bars = _provider(_fixture_handler).daily_adjusted("SYNX", start=START, end=END)
    assert [bar.day for bar in bars] == [
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
    ], "out-of-range 2026-06-30 bar must be filtered; output sorted ascending"
    split_day = bars[0]
    assert split_day.adjusted_close == Decimal("100.55")
    assert split_day.split_factor == Decimal("2.0")
    dividend_day = bars[1]
    assert dividend_day.dividend == Decimal("0.25")
    assert dividend_day.volume == 980000
    assert all(isinstance(bar.adjusted_close, Decimal) for bar in bars)


def test_missing_adjustment_field_fails_closed() -> None:
    payload = json.loads(fixture_bytes("alpha_vantage_daily_adjusted.json"))
    del payload["Time Series (Daily)"]["2026-07-09"]["5. adjusted close"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(MarketDataError, match="FOR-005"):
        _provider(handler).daily_adjusted("SYNX", start=START, end=END)


def test_missing_series_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Note": "rate limited"})

    with pytest.raises(MarketDataError, match="fail closed"):
        _provider(handler).daily_adjusted("SYNX", start=START, end=END)


def test_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(MarketDataError, match="FEL_ALPHAVANTAGE_API_KEY"):
        AlphaVantageMarketDataProvider()


def test_feature_assembly_happy_path_with_mock_provider() -> None:
    rows = assemble_forecast_features(
        MockMarketDataProvider(), "SYNX", start=date(2026, 7, 6), end=date(2026, 7, 10)
    )
    assert len(rows) == 5  # weekdays only
    assert [row.day for row in rows] == sorted(row.day for row in rows)
    assert all(row.adjusted_close > 0 for row in rows)


def test_feature_assembly_rejects_noadj_fail_closed() -> None:
    """T0109/FOR-005: the mock's NOADJ sentinel (missing corporate-action
    adjustments) must reject the whole feature set, never degrade."""
    with pytest.raises(FeatureAssemblyError, match="FOR-005"):
        assemble_forecast_features(
            MockMarketDataProvider(), "NOADJ", start=date(2026, 7, 6), end=date(2026, 7, 10)
        )


class _DeficientProvider:
    """Provider returning bars with a missing adjustment or timestamp."""

    def __init__(self, bar: MarketBar) -> None:
        self._bar = bar

    def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]:
        return [self._bar]


def _bar(**overrides: object) -> MarketBar:
    values: dict[str, object] = {
        "day": date(2026, 7, 6),
        "adjusted_close": Decimal("100"),
        "volume": 1000,
        "dividend": Decimal("0"),
        "split_factor": Decimal("1"),
    }
    values.update(overrides)
    return MarketBar(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"day": None}, "timestamp"),
        ({"adjusted_close": None}, "adjusted close"),
        ({"adjusted_close": Decimal("0")}, "adjusted close"),
        ({"adjusted_close": 100.0}, "adjusted close"),  # binary float is not authoritative
        ({"dividend": None}, "dividend"),
        ({"dividend": Decimal("-1")}, "dividend"),
        ({"split_factor": None}, "split factor"),
        ({"split_factor": Decimal("0")}, "split factor"),
    ],
)
def test_feature_assembly_rejects_deficient_bars(overrides: dict, message: str) -> None:
    provider = _DeficientProvider(_bar(**overrides))
    with pytest.raises(FeatureAssemblyError, match=message):
        assemble_forecast_features(provider, "SYNX", start=START, end=END)


def test_feature_assembly_rejects_duplicate_days() -> None:
    class DuplicatingProvider:
        def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]:
            return [_bar(), _bar()]

    with pytest.raises(FeatureAssemblyError, match="duplicate"):
        assemble_forecast_features(DuplicatingProvider(), "SYNX", start=START, end=END)
