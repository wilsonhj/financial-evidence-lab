"""T0111 (a): temporal-cutoff suite — an ``as_of`` boundary matrix over
documents AND FRED vintages.

Documents half (DB-backed, skips without TEST_DATABASE_URL): synthetic
filings are ingested through the REAL pipeline at three publication
instants, then the REAL corpus API (``GET /v1/entities/{id}/documents``)
is driven through a matrix of cutoffs: pre-publication, boundary-exact
(inclusive ``<=`` semantics), one microsecond before the boundary,
timezone-shifted spellings of the same instant, post-publication, and no
cutoff at all. The no-lookahead invariant — no returned document was
published after the cutoff — is asserted for every cell, and a
quarantined-only document is invisible at EVERY cutoff.

FRED half (no DB): a simulated ALFRED archive with a full revision
history serves a ``LiveFredClient`` via ``httpx.MockTransport``, and the
suite asserts that for a matrix of ``as_of`` instants (midnight-exact,
intraday, tz-shifted) the retrieved vintage equals the archive state at
the fail-closed cutoff day — in particular that a revision published
later on the cutoff's own UTC day is DROPPED (no lookahead ever), and
that tz-shifted spellings of one instant retrieve identical vintages.
"""

from __future__ import annotations

import os
import pathlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import psycopg
import pytest

from fel_providers.mocks import MockStorageProvider
from fel_workers.ingestion.fred import (
    FredIngestionError,
    LiveFredClient,
    ingest_fred_vintage,
    vintage_cutoff_date,
)
from fel_workers.ingestion.pipeline import ingest_filing

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)

# ---------------------------------------------------------------------------
# Documents: as_of boundary matrix through the real pipeline + real API.
# ---------------------------------------------------------------------------

# Publication instants (P2 is deliberately recorded via a +05:30 spelling;
# timestamptz storage must make the spelling irrelevant).
P1 = datetime(2026, 5, 5, 16, 30, tzinfo=UTC)
P2 = datetime(2026, 6, 20, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))  # 06:30Z
P3 = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FEL_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    from app.auth import make_mock_token

    org_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, %s)",
            (org_id, f"org-{org_id[:8]}"),
        )
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'viewer')",
            (org_id, user_id),
        )
    return {"Authorization": f"Bearer {make_mock_token(org_id, user_id, 'viewer')}"}


@pytest.fixture()
def seeded_entity(corpus_conn: psycopg.Connection) -> dict[str, str]:
    """Three parsed documents at P1 < P2 < P3 plus one quarantined-only
    document, all ingested through the REAL pipeline."""
    storage = MockStorageProvider()
    entity_id = str(uuid.uuid4())

    def ingest(name: str, accession: str, published_at: datetime):
        return ingest_filing(
            corpus_conn,
            storage,
            entity_id=entity_id,
            accession=accession,
            source_url=f"https://example.invalid/{accession}.html",
            raw=(FIXTURES / name).read_bytes(),
            published_at=published_at,
            form="10-Q",
        )

    d1 = ingest("synthetic_10q.html", "0009999998-26-000001", P1)
    d2 = ingest("synthetic_10q_stress.html", "0009999998-26-000002", P2)
    d3 = ingest("synthetic_8k_narrative.html", "0009999998-26-000003", P3)
    quarantined = ingest(
        "corrupt_missing_context.html",
        "0009999998-26-000004",
        datetime(2026, 1, 2, tzinfo=UTC),  # earliest instant: pre-dates every cutoff
    )
    outcomes = {"d1": d1, "d2": d2, "d3": d3}
    for outcome in outcomes.values():
        if outcome.status != "succeeded":  # pragma: no cover — seed guard
            raise RuntimeError(f"seed ingestion failed: {outcome!r}")
    if quarantined.status != "quarantined":  # pragma: no cover — seed guard
        raise RuntimeError(f"expected quarantine, got {quarantined!r}")
    ids = {key: str(outcome.document_id) for key, outcome in outcomes.items()}
    ids["entity_id"] = entity_id
    ids["quarantined"] = str(quarantined.document_id)
    return ids


# (as_of query value, expected document keys in publication order)
AS_OF_MATRIX: list[tuple[str | None, list[str]]] = [
    # Pre-publication: cutoff strictly before the first publication.
    ("2026-05-05T16:29:59.999999+00:00", []),
    # Boundary-inclusive: the exact publication instant IS visible (<=).
    ("2026-05-05T16:30:00+00:00", ["d1"]),
    # The same boundary instant spelled in other timezones.
    ("2026-05-05T21:30:00+05:00", ["d1"]),
    ("2026-05-05T11:30:00-05:00", ["d1"]),
    ("2026-05-05T16:30:00Z", ["d1"]),
    # One microsecond before the second publication instant (06:30Z).
    ("2026-06-20T06:29:59.999999+00:00", ["d1"]),
    # The second boundary, in UTC and in its original +05:30 spelling.
    ("2026-06-20T06:30:00+00:00", ["d1", "d2"]),
    ("2026-06-20T12:00:00+05:30", ["d1", "d2"]),
    # Between P2 and P3 (P3 is a midnight-exact publication).
    ("2026-06-30T23:59:59.999999+00:00", ["d1", "d2"]),
    ("2026-07-01T00:00:00+00:00", ["d1", "d2", "d3"]),
    # Same instant as P3 spelled with a +05:45 (Nepal) offset.
    ("2026-07-01T05:45:00+05:45", ["d1", "d2", "d3"]),
    # Far future: everything published is visible.
    ("2027-01-01T00:00:00+00:00", ["d1", "d2", "d3"]),
    # No cutoff: everything, ordered by publication time.
    (None, ["d1", "d2", "d3"]),
]


@requires_db
@pytest.mark.parametrize(("as_of", "expected_keys"), AS_OF_MATRIX)
def test_documents_as_of_boundary_matrix(
    api_client, auth_headers: dict[str, str], seeded_entity: dict[str, str], as_of, expected_keys
) -> None:
    params = {} if as_of is None else {"as_of": as_of}
    response = api_client.get(
        f"/v1/entities/{seeded_entity['entity_id']}/documents",
        headers=auth_headers,
        params=params,
    )
    assert response.status_code == 200
    body = response.json()
    assert [doc["id"] for doc in body] == [seeded_entity[key] for key in expected_keys]
    # No-lookahead invariant on every cell: nothing published after as_of.
    if as_of is not None:
        cutoff = datetime.fromisoformat(as_of)
        for doc in body:
            assert datetime.fromisoformat(doc["published_at"]) <= cutoff
    # The quarantined-only document is NEVER evidence, at any cutoff.
    assert seeded_entity["quarantined"] not in {doc["id"] for doc in body}


@requires_db
def test_naive_as_of_is_rejected(
    api_client, auth_headers: dict[str, str], seeded_entity: dict[str, str]
) -> None:
    """A cutoff without a timezone cannot be compared to publication
    instants; the API must fail closed with a validation error."""
    response = api_client.get(
        f"/v1/entities/{seeded_entity['entity_id']}/documents",
        headers=auth_headers,
        params={"as_of": "2026-06-01T00:00:00"},
    )
    assert response.status_code == 422


@requires_db
def test_quarantined_document_is_invisible_by_id(
    api_client, auth_headers: dict[str, str], seeded_entity: dict[str, str]
) -> None:
    response = api_client.get(f"/v1/documents/{seeded_entity['quarantined']}", headers=auth_headers)
    assert response.status_code == 404
    ok = api_client.get(f"/v1/documents/{seeded_entity['d1']}", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["id"] == seeded_entity["d1"]


# ---------------------------------------------------------------------------
# FRED vintages: simulated ALFRED archive with a full revision history.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Revision:
    """One archived (vintage) publication of an observation."""

    published_on: date  # ALFRED real-time granularity is the DAY
    observed_on: date
    value: str


# Chronological revision history for the synthetic series SYNTEST:
# the 2026-03-01 observation is published, then revised twice.
_ARCHIVE: tuple[_Revision, ...] = (
    _Revision(date(2026, 4, 10), date(2026, 3, 1), "310.0"),
    _Revision(date(2026, 5, 15), date(2026, 3, 1), "311.0"),
    _Revision(date(2026, 5, 15), date(2026, 4, 1), "312.4"),
    _Revision(date(2026, 6, 2), date(2026, 3, 1), "311.5"),
)


def archive_state(vintage_day: date) -> list[tuple[date, str, date]]:
    """(observed_on, value, published_on) as known at the END of
    ``vintage_day`` — the latest publication per observation on or before
    that day, exactly what a date-granular ALFRED window returns."""
    latest: dict[date, _Revision] = {}
    for revision in _ARCHIVE:
        if revision.published_on <= vintage_day:
            current = latest.get(revision.observed_on)
            if current is None or revision.published_on >= current.published_on:
                latest[revision.observed_on] = revision
    return [
        (revision.observed_on, revision.value, revision.published_on)
        for revision in sorted(latest.values(), key=lambda r: r.observed_on)
    ]


def _alfred_handler(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    assert params["realtime_start"] == params["realtime_end"], "window must be pinned to one day"
    vintage_day = date.fromisoformat(params["realtime_start"])
    observations = [
        {"date": observed.isoformat(), "value": value}
        for observed, value, _ in archive_state(vintage_day)
    ]
    # ALFRED reports gaps as '.'; include one so the missing filter runs.
    observations.append({"date": "2026-05-01", "value": "."})
    return httpx.Response(200, json={"observations": observations})


def _client() -> LiveFredClient:
    return LiveFredClient(
        "test-key-not-a-secret",
        transport=httpx.MockTransport(_alfred_handler),
        sleep=lambda seconds: None,
    )


# (as_of instant, expected (observed_on, Decimal value) pairs)
FRED_MATRIX: list[tuple[datetime, list[tuple[date, str]]]] = [
    # Before anything is published: the series does not exist yet.
    (datetime(2026, 4, 10, 12, 0, tzinfo=UTC), []),
    # Publication day fully elapsed at exact midnight: first value visible.
    (datetime(2026, 4, 11, 0, 0, tzinfo=UTC), [(date(2026, 3, 1), "310.0")]),
    # Same instant spelled at +05:00.
    (
        datetime(2026, 4, 11, 5, 0, tzinfo=timezone(timedelta(hours=5))),
        [(date(2026, 3, 1), "310.0")],
    ),
    # Intraday on the 2026-05-15 revision day: the same-day revision is
    # DROPPED (fail closed) — only the 2026-04-10 vintage is visible.
    (datetime(2026, 5, 15, 23, 59, tzinfo=UTC), [(date(2026, 3, 1), "310.0")]),
    # Midnight after the revision day: both revised values appear.
    (
        datetime(2026, 5, 16, 0, 0, tzinfo=UTC),
        [(date(2026, 3, 1), "311.0"), (date(2026, 4, 1), "312.4")],
    ),
    # Between the second and third revisions.
    (
        datetime(2026, 6, 1, 9, 30, tzinfo=UTC),
        [(date(2026, 3, 1), "311.0"), (date(2026, 4, 1), "312.4")],
    ),
    # After the final revision.
    (
        datetime(2026, 6, 15, 9, 30, tzinfo=UTC),
        [(date(2026, 3, 1), "311.5"), (date(2026, 4, 1), "312.4")],
    ),
]


@pytest.mark.parametrize(("as_of", "expected"), FRED_MATRIX)
def test_fred_vintage_boundary_matrix(as_of: datetime, expected: list[tuple[date, str]]) -> None:
    observations = ingest_fred_vintage(_client(), "SYNTEST", as_of=as_of)
    assert [(o.observed_on, str(o.value)) for o in observations] == [
        (observed, value) for observed, value in expected
    ]
    for observation in observations:
        assert observation.as_of == as_of
        assert isinstance(observation.value, Decimal)


@pytest.mark.parametrize(("as_of", "expected"), FRED_MATRIX)
def test_fred_no_lookahead_invariant(as_of: datetime, expected: list[tuple[date, str]]) -> None:
    """Every retrieved value's PUBLICATION day ended at or before the
    cutoff instant — the archive proves no vintage leaked from the future."""
    del expected  # the invariant is checked against the archive itself
    observations = ingest_fred_vintage(_client(), "SYNTEST", as_of=as_of)
    state = {
        (observed, value): published
        for observed, value, published in archive_state(vintage_cutoff_date(as_of))
    }
    for observation in observations:
        published_on = state[(observation.observed_on, str(observation.value))]
        day_end = datetime(
            published_on.year, published_on.month, published_on.day, tzinfo=UTC
        ) + timedelta(days=1)
        assert day_end <= as_of, "a vintage published after the cutoff leaked"


@pytest.mark.parametrize(
    "offset_hours",
    [-12, -7, -5, 0, 3, 5.75, 14],
)
def test_fred_tz_shifted_spellings_retrieve_identical_vintages(offset_hours: float) -> None:
    """One instant, seven spellings: the vintage must be byte-identical."""
    instant = datetime(2026, 5, 16, 0, 0, tzinfo=UTC)
    shifted = instant.astimezone(timezone(timedelta(hours=offset_hours)))
    assert shifted == instant
    assert vintage_cutoff_date(shifted) == vintage_cutoff_date(instant) == date(2026, 5, 15)
    assert ingest_fred_vintage(_client(), "SYNTEST", as_of=shifted) == ingest_fred_vintage(
        _client(), "SYNTEST", as_of=instant
    )


@pytest.mark.parametrize("hour", [0, 1, 12, 23])
@pytest.mark.parametrize("offset_hours", [-12, 0, 14])
def test_vintage_cutoff_day_always_fully_elapsed(hour: int, offset_hours: int) -> None:
    """Pure boundary property over the matrix: the chosen vintage day ends
    at or before as_of, for any wall-clock hour in any timezone."""
    as_of = datetime(2026, 3, 15, hour, tzinfo=timezone(timedelta(hours=offset_hours)))
    cutoff = vintage_cutoff_date(as_of)
    day_end = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=UTC) + timedelta(days=1)
    assert day_end <= as_of.astimezone(UTC)


def test_naive_fred_as_of_fails_closed() -> None:
    with pytest.raises(FredIngestionError, match="timezone-aware"):
        ingest_fred_vintage(_client(), "SYNTEST", as_of=datetime(2026, 5, 16))
    with pytest.raises(FredIngestionError, match="timezone-aware"):
        vintage_cutoff_date(datetime(2026, 5, 16))
