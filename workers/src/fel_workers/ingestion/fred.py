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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

import httpx

from fel_providers.interfaces import FredClient
from fel_workers.http import (
    HttpRequestError,
    RetrievalReceipt,
    ThrottledRetryingClient,
    base_url_host,
)

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
    receipt: RetrievalReceipt | None = field(default=None, compare=False)
    """The fetch this value came from (ADR-0029); None when no retrieval
    happened, e.g. a mock client. Excluded from equality and hashing: an
    observation is its series, day, value and cutoff, so the same vintage
    fetched twice compares equal even though each fetch has its own receipt."""


@runtime_checkable
class ReceiptedFredClient(FredClient, Protocol):
    """Workers-local capability extension of the frozen FredClient protocol.

    ``packages/providers`` is contract-frozen; this adds the retrieval
    receipt (ADR-0029) without touching it, the same way
    ``CompanyFactsSecClient`` extends ``SecClient``.
    """

    def series_vintage_with_receipt(
        self, series_id: str, *, as_of: datetime
    ) -> tuple[list[tuple[date, Decimal]], RetrievalReceipt]: ...


@dataclass(frozen=True)
class FredVintageFetch:
    """One ALFRED response parsed without dropping anything (ADR-0030).

    ``missing`` holds the dates ALFRED returned with its ``"."`` placeholder:
    the vintage covers that date but publishes no value for it. A date that
    is in neither tuple was not in the response at all.
    """

    points: tuple[tuple[date, Decimal], ...]
    missing: tuple[date, ...]
    receipt: RetrievalReceipt


@runtime_checkable
class GapReportingFredClient(ReceiptedFredClient, Protocol):
    """Workers-local capability: report explicit missing values (ADR-0030).

    Extends :class:`ReceiptedFredClient` without touching the frozen
    ``FredClient``, whose ``list[tuple[date, Decimal]]`` cannot carry them.
    """

    def fetch_vintage(self, series_id: str, *, as_of: datetime) -> FredVintageFetch: ...


@dataclass(frozen=True)
class MissingObservation:
    """A date the vintage covers but publishes no value for (ALFRED ``"."``).

    Never a zero or a carried-forward value: the absence itself is the
    record. ``receipt`` is provenance, excluded from equality as on
    :class:`VintageObservation`.
    """

    series_id: str
    observed_on: date
    as_of: datetime
    receipt: RetrievalReceipt | None = field(default=None, compare=False)


@dataclass(frozen=True)
class FredVintageRecord:
    """A series vintage with its published values and its explicit gaps.

    ``missing`` is ``()`` when the source reported no gaps and ``None`` when
    the client cannot report them at all (e.g. a mock): "no gaps" and "not
    known" stay distinguishable.
    """

    series_id: str
    as_of: datetime
    observations: tuple[VintageObservation, ...]
    missing: tuple[MissingObservation, ...] | None


def ingest_fred_vintage_record(
    client: FredClient, series_id: str, *, as_of: datetime
) -> FredVintageRecord:
    """Fetch a series vintage keeping published values and explicit gaps.

    Both tuples are sorted by observation date. ``missing`` is populated only
    for a :class:`GapReportingFredClient`; otherwise it is ``None``.
    """
    if as_of.tzinfo is None:
        raise FredIngestionError(f"as_of cutoff for series {series_id!r} must be timezone-aware")
    receipt: RetrievalReceipt | None = None
    missing_days: tuple[date, ...] | None = None
    if isinstance(client, GapReportingFredClient):
        fetch = client.fetch_vintage(series_id, as_of=as_of)
        points, missing_days, receipt = list(fetch.points), fetch.missing, fetch.receipt
    elif isinstance(client, ReceiptedFredClient):
        points, receipt = client.series_vintage_with_receipt(series_id, as_of=as_of)
    else:
        points = client.series_vintage(series_id, as_of=as_of)
    observations = tuple(
        sorted(
            (
                VintageObservation(
                    series_id=series_id,
                    observed_on=day,
                    value=value,
                    as_of=as_of,
                    receipt=receipt,
                )
                for day, value in points
            ),
            key=lambda item: item.observed_on,
        )
    )
    missing = (
        None
        if missing_days is None
        else tuple(
            MissingObservation(series_id=series_id, observed_on=day, as_of=as_of, receipt=receipt)
            for day in sorted(missing_days)
        )
    )
    return FredVintageRecord(
        series_id=series_id, as_of=as_of, observations=observations, missing=missing
    )


def ingest_fred_vintage(
    client: FredClient, series_id: str, *, as_of: datetime
) -> list[VintageObservation]:
    """Fetch a series vintage through the protocol, sorted by observation date.

    When the client supports :class:`ReceiptedFredClient`, every observation
    carries the receipt of the response it was parsed from. Explicit gaps
    (ALFRED ``"."``) are not returned here; use
    :func:`ingest_fred_vintage_record` to keep them (ADR-0030).

    ``as_of`` must be timezone-aware: a naive cutoff cannot be compared to
    published_at timestamps and would silently break point-in-time queries.
    """
    return list(ingest_fred_vintage_record(client, series_id, as_of=as_of).observations)


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
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
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
            allowed_hosts=base_url_host(base_url),
            secret_query_params=("api_key",),
            sleep=sleep,
            monotonic=monotonic,
            now=now,
        )

    def close(self) -> None:
        self._client.close()

    def series_vintage(self, series_id: str, *, as_of: datetime) -> list[tuple[date, Decimal]]:
        return list(self.fetch_vintage(series_id, as_of=as_of).points)

    def series_vintage_with_receipt(
        self, series_id: str, *, as_of: datetime
    ) -> tuple[list[tuple[date, Decimal]], RetrievalReceipt]:
        """:meth:`series_vintage` plus the receipt for the response (ADR-0029)."""
        fetch = self.fetch_vintage(series_id, as_of=as_of)
        return list(fetch.points), fetch.receipt

    def fetch_vintage(self, series_id: str, *, as_of: datetime) -> FredVintageFetch:
        """Fetch and parse one vintage, keeping explicit gaps (ADR-0030).

        Fails closed on a row that is not an object, lacks ``date`` or
        ``value``, repeats a date, or carries a non-finite value: each would
        otherwise be silently skipped or mis-read.
        """
        if as_of.tzinfo is None:
            raise FredIngestionError(
                f"as_of cutoff for series {series_id!r} must be timezone-aware"
            )
        vintage_date = vintage_cutoff_date(as_of).isoformat()
        try:
            response, receipt = self._client.get_with_receipt(
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
        try:
            payload = response.json()
        except ValueError as exc:
            raise FredIngestionError(f"FRED response for {series_id!r} is not valid JSON") from exc
        raw_observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(raw_observations, list):
            raise FredIngestionError(f"FRED payload for {series_id!r} is missing 'observations'")
        points: list[tuple[date, Decimal]] = []
        missing: list[date] = []
        seen: set[date] = set()
        for item in raw_observations:
            if not isinstance(item, dict) or "date" not in item or "value" not in item:
                raise FredIngestionError(
                    f"FRED observation for {series_id!r} is malformed: {item!r}"
                )
            try:
                day = date.fromisoformat(str(item["date"]))
            except ValueError as exc:
                raise FredIngestionError(
                    f"FRED observation for {series_id!r} is unparseable: {item!r}"
                ) from exc
            if day in seen:
                raise FredIngestionError(
                    f"FRED payload for {series_id!r} repeats observation date {day}"
                )
            seen.add(day)
            value_text = str(item["value"])
            if value_text == _MISSING_VALUE:
                missing.append(day)
                continue
            try:
                value = Decimal(value_text)
            except InvalidOperation as exc:
                raise FredIngestionError(
                    f"FRED observation for {series_id!r} is unparseable: {item!r}"
                ) from exc
            if not value.is_finite():
                raise FredIngestionError(
                    f"FRED observation for {series_id!r} is not a finite number: {item!r}"
                )
            points.append((day, value))
        return FredVintageFetch(points=tuple(points), missing=tuple(missing), receipt=receipt)
