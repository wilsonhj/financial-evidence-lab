"""Vintage-aware FRED ingestion (T0107).

Ingestion always goes through the frozen ``FredClient`` protocol; the
deterministic mock is the default binding, and ``LiveFredClient`` talks to
the ALFRED (archival FRED) API so the ``as_of`` cutoff retrieves the series
exactly as it was published at that instant — never today's revisions
(spec 10.3 point-in-time correctness).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from fel_providers.interfaces import FredClient
from fel_workers.http import HttpRequestError, ThrottledRetryingClient

FRED_BASE_URL = "https://api.stlouisfed.org"
_MISSING_VALUE = "."

# No-lookahead policy (spec 10.3): ALFRED realtime windows are DATE
# granular, so pinning the window to as_of's own calendar date would
# include revisions published later that same day — lookahead. We therefore
# use the day BEFORE the UTC cutoff date; see vintage_cutoff_date().
NO_LOOKAHEAD_LAG_DAYS = 1


def vintage_cutoff_date(as_of: datetime) -> date:
    """UTC-normalized, fail-closed ALFRED realtime date for an ``as_of``.

    ``as_of`` is normalized to UTC first (a wall-clock date in as_of's own
    timezone would shift the vintage day across timezones), then the policy
    date is ``as_of_utc.date() - NO_LOOKAHEAD_LAG_DAYS``: the latest whole
    UTC day guaranteed to be fully elapsed at the cutoff. For an exact
    midnight (end-of-day-exclusive) cutoff this is precisely the last
    complete day; for an intraday cutoff it deliberately DROPS any vintage
    published earlier the same day. That conservative data loss is
    accepted — NO LOOKAHEAD EVER is the invariant, and a date-granular API
    cannot split a day.
    """
    if as_of.tzinfo is None:
        raise FredIngestionError("as_of cutoff must be timezone-aware")
    as_of_utc = as_of.astimezone(UTC)
    return as_of_utc.date() - timedelta(days=NO_LOOKAHEAD_LAG_DAYS)


class FredIngestionError(Exception):
    """A FRED request or payload was invalid."""


@dataclass(frozen=True)
class VintageObservation:
    """One observation of a series as it was known at ``as_of``."""

    series_id: str
    observed_on: date
    value: Decimal
    as_of: datetime


def ingest_fred_vintage(
    client: FredClient, series_id: str, *, as_of: datetime
) -> list[VintageObservation]:
    """Fetch a series vintage through the protocol, sorted by observation date.

    ``as_of`` must be timezone-aware: a naive cutoff cannot be compared to
    published_at timestamps and would silently break point-in-time queries.
    """
    if as_of.tzinfo is None:
        raise FredIngestionError(f"as_of cutoff for series {series_id!r} must be timezone-aware")
    points = client.series_vintage(series_id, as_of=as_of)
    observations = [
        VintageObservation(series_id=series_id, observed_on=day, value=value, as_of=as_of)
        for day, value in points
    ]
    observations.sort(key=lambda item: item.observed_on)
    return observations


class LiveFredClient:
    """FredClient over the ALFRED real-time API. Env (live): FEL_FRED_API_KEY.

    ``realtime_start``/``realtime_end`` are pinned to the fail-closed
    :func:`vintage_cutoff_date` (UTC-normalized, one day before the cutoff
    date) so the response can never include a revision published after —
    or later on the same day as — the ``as_of`` instant. Requests go
    through the shared throttled/retrying HTTP helper. Tests inject an
    ``httpx.MockTransport``; never live in CI.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = FRED_BASE_URL,
        timeout_seconds: float = 30.0,
        min_interval_seconds: float = 0.5,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        key = api_key or os.environ.get("FEL_FRED_API_KEY")
        if not key:
            raise FredIngestionError("FEL_FRED_API_KEY is not configured")
        self._api_key = key
        self._base_url = base_url
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

    def series_vintage(self, series_id: str, *, as_of: datetime) -> list[tuple[date, Decimal]]:
        if as_of.tzinfo is None:
            raise FredIngestionError(
                f"as_of cutoff for series {series_id!r} must be timezone-aware"
            )
        vintage_date = vintage_cutoff_date(as_of).isoformat()
        try:
            response = self._client.get(
                f"{self._base_url}/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "realtime_start": vintage_date,
                    "realtime_end": vintage_date,
                },
            )
        except HttpRequestError as exc:
            raise FredIngestionError(
                f"FRED observations request for {series_id!r} failed: {exc}"
            ) from exc
        payload = response.json()
        raw_observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(raw_observations, list):
            raise FredIngestionError(f"FRED payload for {series_id!r} is missing 'observations'")
        points: list[tuple[date, Decimal]] = []
        for item in raw_observations:
            if not isinstance(item, dict):
                continue
            value_text = str(item.get("value", _MISSING_VALUE))
            if value_text == _MISSING_VALUE:
                continue
            try:
                points.append((date.fromisoformat(str(item.get("date"))), Decimal(value_text)))
            except (ValueError, InvalidOperation) as exc:
                raise FredIngestionError(
                    f"FRED observation for {series_id!r} is unparseable: {item!r}"
                ) from exc
        return points
