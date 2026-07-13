"""Alpha Vantage BYO market-data adapter (T0108, FR-ING-008) and fail-closed
forecast-feature assembly (T0109, FOR-005).

The adapter implements the frozen ``MarketDataProvider`` protocol over the
TIME_SERIES_DAILY_ADJUSTED endpoint with the caller's own key
(FEL_ALPHAVANTAGE_API_KEY). Missing adjustment fields are a hard error —
FOR-005 forbids silently substituting unadjusted prices. Tests inject an
``httpx.MockTransport`` over synthetic fixture JSON; never live in CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from fel_providers.interfaces import MarketBar, MarketDataProvider

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co"
_SERIES_KEY = "Time Series (Daily)"
_FIELD_ADJUSTED_CLOSE = "5. adjusted close"
_FIELD_VOLUME = "6. volume"
_FIELD_DIVIDEND = "7. dividend amount"
_FIELD_SPLIT = "8. split coefficient"


class MarketDataError(Exception):
    """Provider request failed or returned data without required adjustments."""


class FeatureAssemblyError(Exception):
    """FOR-005: forecast features cannot be assembled from deficient bars."""


@dataclass(frozen=True)
class ForecastFeatureRow:
    """One validated daily feature row (decimal prices end-to-end)."""

    day: date
    adjusted_close: Decimal
    volume: int
    dividend: Decimal
    split_factor: Decimal


class AlphaVantageMarketDataProvider:
    """MarketDataProvider over Alpha Vantage daily adjusted series."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = ALPHAVANTAGE_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get("FEL_ALPHAVANTAGE_API_KEY")
        if not key:
            raise MarketDataError("FEL_ALPHAVANTAGE_API_KEY is not configured")
        self._api_key = key
        self._base_url = base_url
        self._client = httpx.Client(transport=transport, timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]:
        response = self._client.get(
            f"{self._base_url}/query",
            params={
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": ticker,
                "outputsize": "full",
                "datatype": "json",
                "apikey": self._api_key,
            },
        )
        if response.status_code >= 400:
            raise MarketDataError(
                f"Alpha Vantage request for {ticker!r} failed with status "
                f"{response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise MarketDataError(f"Alpha Vantage returned a non-object payload for {ticker!r}")
        if "Error Message" in payload:
            raise MarketDataError(f"Alpha Vantage rejected the request for {ticker!r}")
        series = payload.get(_SERIES_KEY)
        if not isinstance(series, dict):
            raise MarketDataError(
                f"Alpha Vantage payload for {ticker!r} is missing "
                f"'{_SERIES_KEY}'; adjusted data is unavailable (fail closed)"
            )
        bars: list[MarketBar] = []
        for day_text, fields in series.items():
            try:
                day = date.fromisoformat(str(day_text))
            except ValueError as exc:
                raise MarketDataError(
                    f"Alpha Vantage bar for {ticker!r} has unparseable date {day_text!r}"
                ) from exc
            if day < start or day > end:
                continue
            if not isinstance(fields, dict):
                raise MarketDataError(f"Alpha Vantage bar {ticker!r}/{day_text} is not an object")
            missing = [
                name
                for name in (_FIELD_ADJUSTED_CLOSE, _FIELD_VOLUME, _FIELD_DIVIDEND, _FIELD_SPLIT)
                if name not in fields
            ]
            if missing:
                raise MarketDataError(
                    f"Alpha Vantage bar {ticker!r}/{day_text} is missing required "
                    f"adjustment fields {missing}; refusing unadjusted data "
                    "(FOR-005 fail closed)"
                )
            try:
                bars.append(
                    MarketBar(
                        day=day,
                        adjusted_close=Decimal(str(fields[_FIELD_ADJUSTED_CLOSE])),
                        volume=int(str(fields[_FIELD_VOLUME])),
                        dividend=Decimal(str(fields[_FIELD_DIVIDEND])),
                        split_factor=Decimal(str(fields[_FIELD_SPLIT])),
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                raise MarketDataError(
                    f"Alpha Vantage bar {ticker!r}/{day_text} has unparseable values"
                ) from exc
        bars.sort(key=lambda bar: bar.day)
        return bars


def assemble_forecast_features(
    provider: MarketDataProvider, ticker: str, *, start: date, end: date
) -> list[ForecastFeatureRow]:
    """Assemble validated forecast features; fail closed on deficient bars.

    FOR-005: bars whose adjustments or timestamps are missing or invalid are
    rejected outright — the feature set is never silently built from
    unadjusted or partially-adjusted prices. Provider-level refusals (e.g.
    the mock's NOADJ sentinel) surface as :class:`FeatureAssemblyError`.
    """
    try:
        bars = provider.daily_adjusted(ticker, start=start, end=end)
    except (ValueError, MarketDataError) as exc:
        raise FeatureAssemblyError(
            f"FOR-005 fail closed for {ticker!r}: required adjustments are " f"unavailable ({exc})"
        ) from exc
    rows: list[ForecastFeatureRow] = []
    seen: set[date] = set()
    for bar in bars:
        if not isinstance(bar.day, date):
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}: bar has no valid timestamp"
            )
        if bar.day in seen:
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}: duplicate bar for {bar.day}"
            )
        if not isinstance(bar.adjusted_close, Decimal) or bar.adjusted_close <= 0:
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}/{bar.day}: adjusted close "
                "is missing or non-positive"
            )
        if not isinstance(bar.dividend, Decimal) or bar.dividend < 0:
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}/{bar.day}: dividend "
                "adjustment is missing or negative"
            )
        if not isinstance(bar.split_factor, Decimal) or bar.split_factor <= 0:
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}/{bar.day}: split factor "
                "is missing or non-positive"
            )
        seen.add(bar.day)
        rows.append(
            ForecastFeatureRow(
                day=bar.day,
                adjusted_close=bar.adjusted_close,
                volume=bar.volume,
                dividend=bar.dividend,
                split_factor=bar.split_factor,
            )
        )
    rows.sort(key=lambda row: row.day)
    return rows
