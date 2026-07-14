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
import time
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from fel_providers.interfaces import MarketBar, MarketDataProvider
from fel_workers.http import HttpRequestError, ThrottledRetryingClient

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co"
_SERIES_KEY = "Time Series (Daily)"
_FIELD_ADJUSTED_CLOSE = "5. adjusted close"
_FIELD_VOLUME = "6. volume"
_FIELD_DIVIDEND = "7. dividend amount"
_FIELD_SPLIT = "8. split coefficient"

# Alpha Vantage's compact output covers the latest ~100 trading days; when
# the requested window starts within this many calendar days of today the
# cheaper compact payload suffices, otherwise fetch full history.
COMPACT_WINDOW_DAYS = 100


class MarketDataError(Exception):
    """Provider request failed or returned data without required adjustments."""


class FeatureAssemblyError(Exception):
    """FOR-005: forecast features cannot be assembled from deficient bars."""


# A validated forecast feature row IS a validated market bar — the previous
# hand-copied mirror dataclass drifted for no benefit, so the frozen
# contract dataclass is reused directly (decimal prices end-to-end).
ForecastFeatureRow = MarketBar


class AlphaVantageMarketDataProvider:
    """MarketDataProvider over Alpha Vantage daily adjusted series.

    Requests go through the shared throttled/retrying HTTP helper;
    ``transport``/``sleep``/``monotonic``/``today`` are injectable for
    deterministic tests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = ALPHAVANTAGE_BASE_URL,
        timeout_seconds: float = 30.0,
        min_interval_seconds: float = 0.5,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        key = api_key or os.environ.get("FEL_ALPHAVANTAGE_API_KEY")
        if not key:
            raise MarketDataError("FEL_ALPHAVANTAGE_API_KEY is not configured")
        self._api_key = key
        self._base_url = base_url
        self._today = today
        self._client = ThrottledRetryingClient(
            transport=transport,
            timeout_seconds=timeout_seconds,
            min_interval_seconds=min_interval_seconds,
            max_retries=max_retries,
            sleep=sleep,
            monotonic=monotonic,
        )

    def close(self) -> None:
        self._client.close()

    def _outputsize(self, start: date) -> str:
        """compact when the window is within the last ~100 calendar days."""
        if start >= self._today() - timedelta(days=COMPACT_WINDOW_DAYS):
            return "compact"
        return "full"

    def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]:
        try:
            response = self._client.get(
                f"{self._base_url}/query",
                params={
                    "function": "TIME_SERIES_DAILY_ADJUSTED",
                    "symbol": ticker,
                    "outputsize": self._outputsize(start),
                    "datatype": "json",
                    "apikey": self._api_key,
                },
            )
        except HttpRequestError as exc:
            raise MarketDataError(f"Alpha Vantage request for {ticker!r} failed: {exc}") from exc
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
        rows.append(bar)
    rows.sort(key=lambda row: row.day)
    return rows
