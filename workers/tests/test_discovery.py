"""T0101: filing discovery through the injected SecClient protocol."""

from __future__ import annotations

import json
import os
import pathlib
from datetime import date, datetime

import psycopg
import pytest

from fel_workers.ingestion.discovery import (
    JOB_KIND_SEC_FILING_FETCH,
    DiscoveryError,
    discover_filings,
    run_discovery_job,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)


class FixtureSecClient:
    """SecClient over the committed synthetic submissions fixture."""

    def submissions(self, cik: str) -> dict[str, object]:
        payload = json.loads(fixture_bytes("sec_submissions_synthetic.json"))
        assert isinstance(payload, dict)
        return payload

    def fetch_document(self, url: str) -> bytes:
        return b"<html></html>"


def test_discover_filings_lists_issuer_filings() -> None:
    refs = discover_filings(FixtureSecClient(), "9999999")
    assert [r.accession for r in refs] == [
        "0009999999-26-000010",
        "0009999999-26-000007",
        "0009999999-25-000042",
    ]
    first = refs[0]
    assert first.form == "10-Q"
    assert first.filed_on == date(2026, 5, 5)
    assert first.cik == "0009999999"
    assert first.primary_document_url == (
        "https://www.sec.gov/Archives/edgar/data/9999999/000999999926000010/synx-20260331.htm"
    )


def test_discover_filings_filters_forms() -> None:
    refs = discover_filings(FixtureSecClient(), "9999999", forms=frozenset({"10-K"}))
    assert [r.form for r in refs] == ["10-K"]


def test_discover_filings_rejects_malformed_payload() -> None:
    class BrokenClient:
        def submissions(self, cik: str) -> dict[str, object]:
            return {"cik": cik}

        def fetch_document(self, url: str) -> bytes:
            return b""

    with pytest.raises(DiscoveryError, match="filings"):
        discover_filings(BrokenClient(), "9999999")


@requires_db
def test_discovery_job_enqueues_idempotent_fetches(corpus_conn: psycopg.Connection) -> None:
    refs = run_discovery_job(corpus_conn, FixtureSecClient(), {"cik": "9999999"})
    assert len(refs) == 3
    # Re-running discovery must not duplicate fetch jobs (accession-keyed).
    run_discovery_job(corpus_conn, FixtureSecClient(), {"cik": "9999999"})
    count = corpus_conn.execute(
        "SELECT count(*) FROM jobs WHERE kind = %s", (JOB_KIND_SEC_FILING_FETCH,)
    ).fetchone()
    assert count is not None and count[0] == 3
    payload = corpus_conn.execute(
        "SELECT payload FROM jobs WHERE idempotency_key = %s",
        ("sec-fetch|0009999999-26-000010",),
    ).fetchone()
    assert payload is not None
    assert payload[0]["form"] == "10-Q"
    assert datetime.fromisoformat(payload[0]["filed_on"]).date() == date(2026, 5, 5)
