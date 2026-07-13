"""Vintage-aware FRED ingestion (T0107).

Ingestion always goes through the frozen ``FredClient`` protocol; the
deterministic mock is the default binding, and ``LiveFredClient`` talks to
the ALFRED (archival FRED) API so the ``as_of`` cutoff retrieves the series
exactly as it was published at that instant — never today's revisions
(spec 10.3 point-in-time correctness).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from fel_providers.interfaces import FredClient

FRED_BASE_URL = "https://api.stlouisfed.org"
_MISSING_VALUE = "."


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

    ``realtime_start``/``realtime_end`` are pinned to the ``as_of`` date so
    the response is the vintage visible at the cutoff, not the latest
    revision. Tests inject an ``httpx.MockTransport``; never live in CI.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = FRED_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get("FEL_FRED_API_KEY")
        if not key:
            raise FredIngestionError("FEL_FRED_API_KEY is not configured")
        self._api_key = key
        self._base_url = base_url
        self._client = httpx.Client(transport=transport, timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def series_vintage(self, series_id: str, *, as_of: datetime) -> list[tuple[date, Decimal]]:
        if as_of.tzinfo is None:
            raise FredIngestionError(
                f"as_of cutoff for series {series_id!r} must be timezone-aware"
            )
        vintage_date = as_of.date().isoformat()
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
        if response.status_code >= 400:
            raise FredIngestionError(
                f"FRED observations request for {series_id!r} failed with "
                f"status {response.status_code}"
            )
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
