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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

import httpx

from fel_providers.interfaces import MarketBar, MarketDataProvider
from fel_workers.http import (
    HttpRequestError,
    RetrievalReceipt,
    ThrottledRetryingClient,
    base_url_host,
    read_source_clocks,
)

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co"
_SERIES_KEY = "Time Series (Daily)"
_FIELD_ADJUSTED_CLOSE = "5. adjusted close"
_FIELD_VOLUME = "6. volume"
_FIELD_DIVIDEND = "7. dividend amount"
_FIELD_SPLIT = "8. split coefficient"
# Clocks Alpha Vantage reports in "Meta Data" (ADR-0031). The time zone is
# kept beside the refresh date because the date alone does not name one.
ALPHAVANTAGE_SOURCE_CLOCKS: dict[str, tuple[str, ...]] = {
    "last_refreshed": ("Meta Data", "3. Last Refreshed"),
    "time_zone": ("Meta Data", "5. Time Zone"),
}
# Alpha Vantage reports throttling and plan entitlement refusals as HTTP 200
# with one of these keys instead of data. That is a provider refusal, not
# evidence that the series lacks adjustments, so it gets its own error.
_REFUSAL_KEYS = ("Note", "Information")

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


@runtime_checkable
class ReceiptedMarketDataProvider(MarketDataProvider, Protocol):
    """Workers-local capability extension of the frozen MarketDataProvider.

    Adds the retrieval receipt (ADR-0029) without touching
    ``packages/providers``; ``MarketBar`` stays the frozen row contract.
    """

    def daily_adjusted_with_receipt(
        self, ticker: str, *, start: date, end: date
    ) -> tuple[list[MarketBar], RetrievalReceipt]: ...


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
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
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
            allowed_hosts=base_url_host(base_url),
            secret_query_params=("apikey",),
            sleep=sleep,
            monotonic=monotonic,
            now=now,
        )

    def close(self) -> None:
        self._client.close()

    def _outputsize(self, start: date) -> str:
        """compact when the window is within the last ~100 calendar days."""
        if start >= self._today() - timedelta(days=COMPACT_WINDOW_DAYS):
            return "compact"
        return "full"

    def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]:
        bars, _receipt = self.daily_adjusted_with_receipt(ticker, start=start, end=end)
        return bars

    def daily_adjusted_with_receipt(
        self, ticker: str, *, start: date, end: date
    ) -> tuple[list[MarketBar], RetrievalReceipt]:
        """:meth:`daily_adjusted` plus the receipt for the response (ADR-0029)."""
        try:
            response, receipt = self._client.get_with_receipt(
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
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketDataError(
                f"Alpha Vantage response for {ticker!r} is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise MarketDataError(f"Alpha Vantage returned a non-object payload for {ticker!r}")
        receipt = receipt.with_source_clocks(
            read_source_clocks(payload, ALPHAVANTAGE_SOURCE_CLOCKS)
        )
        if "Error Message" in payload:
            raise MarketDataError(f"Alpha Vantage rejected the request for {ticker!r}")
        refusal = next((key for key in _REFUSAL_KEYS if key in payload), None)
        if refusal is not None and _SERIES_KEY not in payload:
            # The upstream text is not echoed: it is free-form and unbounded.
            raise MarketDataError(
                f"Alpha Vantage refused the request for {ticker!r} ({refusal!r}: "
                "rate limit or plan entitlement); no data was returned"
            )
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
                adjusted_close = Decimal(str(fields[_FIELD_ADJUSTED_CLOSE]))
                dividend = Decimal(str(fields[_FIELD_DIVIDEND]))
                split_factor = Decimal(str(fields[_FIELD_SPLIT]))
                volume = int(str(fields[_FIELD_VOLUME]))
            except (InvalidOperation, ValueError) as exc:
                raise MarketDataError(
                    f"Alpha Vantage bar {ticker!r}/{day_text} has unparseable values"
                ) from exc
            for label, magnitude in (
                ("adjusted close", adjusted_close),
                ("dividend", dividend),
                ("split factor", split_factor),
            ):
                if not magnitude.is_finite():
                    raise MarketDataError(
                        f"Alpha Vantage bar {ticker!r}/{day_text} has a non-finite {label}"
                    )
            bars.append(
                MarketBar(
                    day=day,
                    adjusted_close=adjusted_close,
                    volume=volume,
                    dividend=dividend,
                    split_factor=split_factor,
                )
            )
        bars.sort(key=lambda bar: bar.day)
        return bars, receipt


def assemble_forecast_features(
    provider: MarketDataProvider, ticker: str, *, start: date, end: date
) -> list[ForecastFeatureRow]:
    """Assemble validated forecast features; fail closed on deficient bars.

    FOR-005: bars whose adjustments or timestamps are missing or invalid are
    rejected outright — the feature set is never silently built from
    unadjusted or partially-adjusted prices. Provider-level refusals (e.g.
    the mock's NOADJ sentinel) surface as :class:`FeatureAssemblyError`.
    """
    rows, _receipt = assemble_receipted_forecast_features(provider, ticker, start=start, end=end)
    return rows


def assemble_receipted_forecast_features(
    provider: MarketDataProvider, ticker: str, *, start: date, end: date
) -> tuple[list[ForecastFeatureRow], RetrievalReceipt | None]:
    """:func:`assemble_forecast_features` plus the receipt of the fetch.

    The receipt (ADR-0029) is None when the provider has no
    :class:`ReceiptedMarketDataProvider` capability, e.g. the mock; the
    FOR-005 validation is identical either way.
    """
    receipt: RetrievalReceipt | None = None
    try:
        if isinstance(provider, ReceiptedMarketDataProvider):
            bars, receipt = provider.daily_adjusted_with_receipt(ticker, start=start, end=end)
        else:
            bars = provider.daily_adjusted(ticker, start=start, end=end)
    except MarketDataError as exc:
        raise FeatureAssemblyError(
            f"FOR-005 fail closed for {ticker!r}: required adjustments are unavailable ({exc})"
        ) from exc
    except ValueError as exc:
        # The mock's NOADJ sentinel raises ValueError. A receipted provider's
        # ValueError is a caller bug (for example a naive receipt clock), not
        # missing adjustments, so it must not be rewritten as FOR-005.
        if isinstance(provider, ReceiptedMarketDataProvider):
            raise
        raise FeatureAssemblyError(
            f"FOR-005 fail closed for {ticker!r}: required adjustments are unavailable ({exc})"
        ) from exc
    return _validated_feature_rows(ticker, bars), receipt


def _validated_feature_rows(ticker: str, bars: list[MarketBar]) -> list[ForecastFeatureRow]:
    """FOR-005 row validation shared by both assembly entry points."""
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
        if (
            not isinstance(bar.adjusted_close, Decimal)
            or not bar.adjusted_close.is_finite()
            or bar.adjusted_close <= 0
        ):
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}/{bar.day}: adjusted close "
                "is missing, non-finite, or non-positive"
            )
        if (
            not isinstance(bar.dividend, Decimal)
            or not bar.dividend.is_finite()
            or bar.dividend < 0
        ):
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}/{bar.day}: dividend "
                "adjustment is missing, non-finite, or negative"
            )
        if (
            not isinstance(bar.split_factor, Decimal)
            or not bar.split_factor.is_finite()
            or bar.split_factor <= 0
        ):
            raise FeatureAssemblyError(
                f"FOR-005 fail closed for {ticker!r}/{bar.day}: split factor "
                "is missing, non-finite, or non-positive"
            )
        seen.add(bar.day)
        rows.append(bar)
    rows.sort(key=lambda row: row.day)
    return rows
