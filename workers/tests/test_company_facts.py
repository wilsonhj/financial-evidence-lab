"""Issue #83: SEC companyfacts ingestion as stored corpus documents.

Everything runs over the committed LABELED SYNTHETIC fixture
(``companyfacts_synthetic.json``, fictional issuer CIK 9999999) — live
requests are mocked with ``httpx.MockTransport``; nothing ever leaves the
process. DB-backed tests exercise the real store -> parse -> normalize ->
persist pipeline against Postgres.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import psycopg
import pytest

from fel_providers.mocks import MockStorageProvider
from fel_workers import queue
from fel_workers.consumer import run_worker
from fel_workers.ingestion.company_facts import (
    COMPANY_FACTS_FORM,
    COMPANY_FACTS_MIME_TYPE,
    COMPANY_FACTS_NORMALIZER_VERSION,
    COMPANY_FACTS_PARSER_VERSION,
    JOB_KIND_SEC_COMPANY_FACTS,
    CompanyFactsSecClient,
    canonical_company_facts_bytes,
    company_facts_accession,
    enqueue_company_facts,
    entity_id_for_cik,
    handle_sec_company_facts,
    ingest_company_facts,
    normalize_company_facts,
    parse_company_facts,
)
from fel_workers.ingestion.errors import IngestError, NormalizationError, ParseError
from fel_workers.ingestion.pipeline import _prior_canonical_facts, ingest_filing
from fel_workers.ingestion.sec_client import SEC_USER_AGENT, LiveSecClient, SecFetchError

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)

CIK = "9999999"
ENTITY_ID = entity_id_for_cik(CIK)
FETCHED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def companyfacts_raw() -> bytes:
    """Fixture payload as the deterministic bytes the handler would store."""
    payload = json.loads(fixture_bytes("companyfacts_synthetic.json"), parse_float=Decimal)
    assert isinstance(payload, dict)
    return canonical_company_facts_bytes(payload)


class FixtureCompanyFactsClient:
    """CompanyFacts-capable SecClient over the committed synthetic fixture."""

    def submissions(self, cik: str) -> dict[str, object]:
        payload = json.loads(fixture_bytes("sec_submissions_synthetic.json"))
        assert isinstance(payload, dict)
        return payload

    def fetch_document(self, url: str) -> bytes:
        return fixture_bytes("synthetic_10q.html")

    def company_facts(self, cik: str) -> dict[str, object]:
        payload = json.loads(fixture_bytes("companyfacts_synthetic.json"), parse_float=Decimal)
        assert isinstance(payload, dict)
        return payload


class PlainSecClient:
    """SecClient WITHOUT the company_facts capability (dispatch narrowing)."""

    def submissions(self, cik: str) -> dict[str, object]:
        return {"cik": cik}

    def fetch_document(self, url: str) -> bytes:
        return b"<html><p>plain</p></html>"


# --- live client (httpx.MockTransport; never live) --------------------------


def test_live_client_company_facts_url_and_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=fixture_bytes("companyfacts_synthetic.json"))

    client = LiveSecClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None, monotonic=lambda: 0.0
    )
    payload = client.company_facts(CIK)
    assert str(seen[0].url) == "https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json"
    assert seen[0].headers["User-Agent"] == SEC_USER_AGENT
    assert payload["cik"] == 9999999


def test_live_client_company_facts_rejects_non_object_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[1, 2]")

    client = LiveSecClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None, monotonic=lambda: 0.0
    )
    with pytest.raises(SecFetchError, match="non-object"):
        client.company_facts(CIK)


def test_live_client_preserves_non_float_exact_decimals() -> None:
    """Regression (#88 review): response.json() float-decodes, then
    canonical_company_facts_bytes re-dumps corrupted IEEE-754 values into the
    stored corpus. High-magnitude decimals that float cannot represent must
    survive the live-client → handler path unchanged (AGENTS.md deterministic
    finance; issue #83 real-bytes ruling)."""
    # 999999999999999.99 is not exactly representable as binary float —
    # json.loads without parse_float=Decimal yields 1000000000000000.0.
    wire = (
        b'{"cik":9999999,"facts":{"us-gaap":{"Assets":{"units":{"USD":'
        b'[{"end":"2025-12-31","val":999999999999999.99,"accn":"a","form":"10-K"}]}}}}}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=wire)

    client = LiveSecClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None, monotonic=lambda: 0.0
    )
    payload = client.company_facts(CIK)
    val = payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"]  # type: ignore[index]
    assert val == Decimal("999999999999999.99")
    assert not isinstance(val, float)

    stored = canonical_company_facts_bytes(payload)
    assert b"999999999999999.99" in stored
    assert b"1000000000000000" not in stored


@requires_db
def test_handler_stores_decimal_faithful_live_payload(
    corpus_conn: psycopg.Connection,
) -> None:
    """Live fetch → handle_sec_company_facts must persist the exact decimal."""
    wire = (
        b'{"cik":9999999,"facts":{"us-gaap":{"Assets":{"units":{"USD":'
        b'[{"end":"2025-12-31","val":999999999999999.99,"accn":"a","form":"10-K"}]}}}}}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=wire)

    client = LiveSecClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None, monotonic=lambda: 0.0
    )
    outcome = handle_sec_company_facts(corpus_conn, MockStorageProvider(), client, {"cik": CIK})
    assert outcome.status == "succeeded"
    row = corpus_conn.execute(
        "SELECT value FROM financial_facts WHERE concept = %s",
        ("us-gaap:Assets",),
    ).fetchone()
    assert row is not None
    assert row[0] == "999999999999999.99"


def test_capability_protocol_runtime_narrowing() -> None:
    assert isinstance(FixtureCompanyFactsClient(), CompanyFactsSecClient)
    assert not isinstance(PlainSecClient(), CompanyFactsSecClient)


# --- snapshot accessions -----------------------------------------------------


def test_company_facts_accession_is_snapshot_scoped() -> None:
    raw = companyfacts_raw()
    digest = hashlib.sha256(raw).hexdigest()
    accession = company_facts_accession(CIK, FETCHED_AT, f"sha256:{digest}")
    assert accession == f"COMPANYFACTS-0009999999-2026-05-20-{digest[:8]}"
    # The UTC date is snapshot-scoped: a fetch instant late in another zone's
    # day still keys on the UTC calendar date.
    late = datetime(2026, 5, 20, 23, 59, tzinfo=UTC)
    assert company_facts_accession(CIK, late, f"sha256:{digest}").split("-", 5)[1:5] == [
        "0009999999",
        "2026",
        "05",
        "20",
    ]
    with pytest.raises(ValueError, match="timezone-aware"):
        company_facts_accession(CIK, datetime(2026, 5, 20, 12, 0), f"sha256:{digest}")


# --- parse: canonical rendering, sections, spans -----------------------------


def test_parse_canonical_text_is_valid_json_and_deterministic() -> None:
    raw = companyfacts_raw()
    first = parse_company_facts(raw)
    second = parse_company_facts(raw)
    assert first.text == second.text
    assert first.parser_version == COMPANY_FACTS_PARSER_VERSION
    # The canonical rendering is itself valid JSON, semantically identical
    # to the source payload.
    assert json.loads(first.text) == json.loads(raw)


def test_parse_builds_one_section_per_taxonomy_concept() -> None:
    parsed = parse_company_facts(companyfacts_raw())
    root = parsed.sections[0]
    assert root.heading_path == ("(document)",)
    assert (root.start_char, root.end_char) == (0, len(parsed.text))
    paths = [section.heading_path for section in parsed.sections[1:]]
    assert paths == [
        ("(document)", "dei", "EntityCommonStockSharesOutstanding"),
        ("(document)", "dei", "EntityRegistrantName"),
        ("(document)", "us-gaap", "Assets"),
        ("(document)", "us-gaap", "EarningsPerShareBasic"),
        ("(document)", "us-gaap", "Revenues"),
    ]
    for section in parsed.sections[1:]:
        assert section.parent_id == root.id
        fragment = parsed.text[section.start_char : section.end_char]
        assert fragment.startswith(f'"{section.heading}"')
        assert fragment.endswith("}")


def test_parse_spans_slice_exact_json_fragments() -> None:
    parsed = parse_company_facts(companyfacts_raw())
    assert len(parsed.spans) == 8  # one per observation, incl. the text-shaped one
    for span in parsed.spans:
        covered = parsed.text[span.start_char : span.end_char]
        assert span.text_hash == "sha256:" + hashlib.sha256(covered.encode()).hexdigest()
        fragment = json.loads(covered)  # each span is a full observation object
        assert isinstance(fragment, dict) and "end" in fragment


def test_parse_skips_text_shaped_values_with_diagnostic() -> None:
    parsed = parse_company_facts(companyfacts_raw())
    assert len(parsed.observations) == 7  # 8 spans minus the text-shaped one
    assert len(parsed.diagnostics) == 1
    assert "EntityRegistrantName" in parsed.diagnostics[0]
    assert "non-numeric" in parsed.diagnostics[0]
    concepts = {obs.concept for obs in parsed.observations}
    assert "dei:EntityRegistrantName" not in concepts


def test_parse_rejects_malformed_json_and_wrong_shapes() -> None:
    with pytest.raises(ParseError, match="not valid JSON") as excinfo:
        parse_company_facts(b"{not json")
    assert excinfo.value.reason_code == "MALFORMED_JSON"
    with pytest.raises(ParseError, match="not a JSON object"):
        parse_company_facts(b"[1, 2]")
    with pytest.raises(ParseError, match="'facts' member"):
        parse_company_facts(b'{"cik": 1, "facts": [1]}')
    with pytest.raises(ParseError, match="not valid UTF-8"):
        parse_company_facts(b"\xff\xfe")


def test_parse_rejects_non_finite_constants_fail_closed() -> None:
    raw = (
        b'{"cik": 9999999, "facts": {"us-gaap": {"Assets": {"label": "Assets",'
        b' "units": {"USD": [{"end": "2025-12-31", "val": NaN,'
        b' "accn": "0009999999-26-000003"}]}}}}}'
    )
    with pytest.raises(NormalizationError, match="non-finite") as excinfo:
        parse_company_facts(raw)
    assert excinfo.value.reason_code == "NONFINITE_FACT_VALUE"


def test_parse_rejects_bad_period_dates() -> None:
    raw = (
        b'{"cik": 9999999, "facts": {"us-gaap": {"Assets": {"units":'
        b' {"USD": [{"end": "not-a-date", "val": 1}]}}}}}'
    )
    with pytest.raises(ParseError, match="unparseable end") as excinfo:
        parse_company_facts(raw)
    assert excinfo.value.reason_code == "INVALID_PERIOD_DATE"
    missing_end = (
        b'{"cik": 9999999, "facts": {"us-gaap": {"Assets": {"units":' b' {"USD": [{"val": 1}]}}}}}'
    )
    with pytest.raises(ParseError) as structural:
        parse_company_facts(missing_end)
    assert structural.value.reason_code == "INVALID_PERIOD_STRUCTURE"


# --- normalize: decimal strings, provenance dimensions, no restatement -------


def test_normalize_produces_decimal_strings_and_periods() -> None:
    parsed = parse_company_facts(companyfacts_raw())
    facts = normalize_company_facts(parsed, entity_id=ENTITY_ID, document_version_id=ENTITY_ID)
    assert len(facts) == 7
    by_concept_value = {(fact.concept, fact.value) for fact in facts}
    assert ("us-gaap:Assets", "5250000.5") in by_concept_value
    assert ("us-gaap:EarningsPerShareBasic", "0.85") in by_concept_value
    assert ("dei:EntityCommonStockSharesOutstanding", "41000000") in by_concept_value
    for fact in facts:
        assert fact.restates is None, "companyfacts never records restatement linkage"
        assert fact.duplicate_of is None
        assert fact.scale == 0
        assert fact.source_span_id
        # Contract decimal-string shape (matches the DB CHECK).
        assert fact.value.lstrip("-").replace(".", "", 1).isdigit()
    revenues = [f for f in facts if f.concept == "us-gaap:Revenues"]
    assert {f.period_type for f in revenues} == {"duration"}
    eps = next(f for f in facts if f.concept == "us-gaap:EarningsPerShareBasic")
    assert eps.unit == "USD/shares"
    assert eps.label == "Earnings Per Share, Basic"


def test_normalize_keys_same_period_by_reporting_provenance() -> None:
    """The fixture reports Assets@2025-12-31 from both the 10-K and the 10-Q
    with different values (a real companyfacts shape); provenance dimensions
    keep them on distinct fact keys instead of failing as an inconsistent
    duplicate."""
    parsed = parse_company_facts(companyfacts_raw())
    facts = normalize_company_facts(parsed, entity_id=ENTITY_ID, document_version_id=ENTITY_ID)
    year_end = [
        f for f in facts if f.concept == "us-gaap:Assets" and str(f.period_instant) == "2025-12-31"
    ]
    assert sorted(f.value for f in year_end) == ["5000000", "5000250"]
    assert {f.dimensions["accn"] for f in year_end} == {
        "0009999999-26-000003",
        "0009999999-26-000010",
    }
    assert len({f.fact_key for f in year_end}) == 2


def test_normalize_conflicting_duplicate_fails_closed() -> None:
    raw = (
        b'{"cik": 9999999, "facts": {"us-gaap": {"Assets": {"units": {"USD": ['
        b'{"end": "2025-12-31", "val": 1, "accn": "a"},'
        b'{"end": "2025-12-31", "val": 2, "accn": "a"}]}}}}}'
    )
    parsed = parse_company_facts(raw)
    with pytest.raises(NormalizationError, match="conflicting values") as excinfo:
        normalize_company_facts(parsed, entity_id=ENTITY_ID, document_version_id=ENTITY_ID)
    assert excinfo.value.reason_code == "INCONSISTENT_DUPLICATE"


def test_normalize_identical_duplicate_collapses() -> None:
    raw = (
        b'{"cik": 9999999, "facts": {"us-gaap": {"Assets": {"units": {"USD": ['
        b'{"end": "2025-12-31", "val": 7, "accn": "a"},'
        b'{"end": "2025-12-31", "val": 7, "accn": "a"}]}}}}}'
    )
    parsed = parse_company_facts(raw)
    facts = normalize_company_facts(parsed, entity_id=ENTITY_ID, document_version_id=ENTITY_ID)
    assert len(facts) == 2
    assert facts[1].duplicate_of == facts[0].id


# --- DB: end-to-end pipeline, snapshotting, isolation, consumer --------------


@requires_db
def test_end_to_end_snapshot_persists_and_reverifies(corpus_conn: psycopg.Connection) -> None:
    """enqueue -> consumer claim -> fetch -> store -> parse -> normalize ->
    persist, then re-verify every span text hash against the immutably
    persisted canonical JSON."""
    storage = MockStorageProvider()
    job_id = enqueue_company_facts(corpus_conn, cik=CIK, job_queue="ingestion")
    # Same CIK + same UTC day replays the same job (kind-namespaced key).
    assert enqueue_company_facts(corpus_conn, cik=CIK, job_queue="ingestion") == job_id
    completed = run_worker(
        corpus_conn, storage, FixtureCompanyFactsClient(), queue_name="ingestion", max_iterations=3
    )
    assert completed == 1
    doc = corpus_conn.execute(
        "SELECT id::text, accession, form, mime_type, source_url, published_at" " FROM documents"
    ).fetchone()
    assert doc is not None
    assert doc[2] == COMPANY_FACTS_FORM
    assert doc[3] == COMPANY_FACTS_MIME_TYPE
    assert doc[1].startswith("COMPANYFACTS-0009999999-")
    assert doc[4] == "https://data.sec.gov/api/xbrl/companyfacts/CIK0009999999.json"
    # Fixture client → handle uses datetime.now(UTC); pin that published_at is
    # timezone-aware UTC (fetch instant), not a naive/filing-date midnight.
    assert doc[5].tzinfo is not None
    assert doc[5].utcoffset().total_seconds() == 0
    version = corpus_conn.execute(
        "SELECT id::text, parser_version, normalizer_version, canonical_text_key"
        " FROM document_versions WHERE status = 'parsed'"
    ).fetchone()
    assert version is not None
    assert version[1] == COMPANY_FACTS_PARSER_VERSION
    assert version[2] == COMPANY_FACTS_NORMALIZER_VERSION
    counts = corpus_conn.execute(
        "SELECT (SELECT count(*) FROM sections), (SELECT count(*) FROM source_spans),"
        " (SELECT count(*) FROM financial_facts), (SELECT count(*) FROM tables_meta)"
    ).fetchone()
    assert counts == (6, 8, 7, 0)
    # Citation integrity: every persisted span re-verifies against the
    # persisted canonical text, byte for byte.
    canonical = storage.get(version[3]).decode()
    spans = corpus_conn.execute(
        "SELECT start_char, end_char, text_hash FROM source_spans"
    ).fetchall()
    for start, end, digest in spans:
        covered = canonical[start:end]
        assert digest == "sha256:" + hashlib.sha256(covered.encode()).hexdigest()
        assert isinstance(json.loads(covered), dict)
    # Every fact cites a span of the document's own canonical text.
    orphans = corpus_conn.execute(
        "SELECT count(*) FROM financial_facts ff LEFT JOIN source_spans s"
        " ON s.id = ff.source_span_id WHERE s.id IS NULL"
    ).fetchone()
    assert orphans is not None and orphans[0] == 0
    values = {row[0] for row in corpus_conn.execute("SELECT value FROM financial_facts").fetchall()}
    assert "5250000.5" in values and "0.85" in values


@requires_db
def test_same_day_refetch_identical_noop_mutated_new_document(
    corpus_conn: psycopg.Connection,
) -> None:
    """Snapshot accessions: byte-identical refetch is a ledger no-op; a
    mutated intra-day refetch becomes a NEW document — never a
    DIVERGENT_ACCESSION_CONTENT quarantine."""
    storage = MockStorageProvider()
    raw = companyfacts_raw()
    first = ingest_company_facts(corpus_conn, storage, cik=CIK, raw=raw, fetched_at=FETCHED_AT)
    assert first.status == "succeeded"
    replay = ingest_company_facts(
        corpus_conn,
        storage,
        cik=CIK,
        raw=raw,
        fetched_at=FETCHED_AT.replace(hour=18),  # same UTC day, later fetch
    )
    assert replay.status == "noop"
    assert replay.document_id == first.document_id
    # data.sec.gov mutated the payload within the same day.
    payload = json.loads(raw, parse_float=Decimal)
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][2]["val"] = 5300000
    mutated = ingest_company_facts(
        corpus_conn,
        storage,
        cik=CIK,
        raw=canonical_company_facts_bytes(payload),
        fetched_at=FETCHED_AT.replace(hour=20),
    )
    assert mutated.status == "succeeded"
    assert mutated.document_id != first.document_id
    documents = corpus_conn.execute("SELECT count(*) FROM documents").fetchone()
    assert documents is not None and documents[0] == 2
    quarantined = corpus_conn.execute("SELECT count(*) FROM ingestion_quarantine").fetchone()
    assert quarantined is not None and quarantined[0] == 0


@requires_db
def test_restatement_isolation_both_directions(corpus_conn: psycopg.Connection) -> None:
    """Filing ingestion never restates against companyfacts values, and
    companyfacts never restates against filing values (issue #83 ruling)."""
    storage = MockStorageProvider()
    snapshot = ingest_company_facts(
        corpus_conn, storage, cik=CIK, raw=companyfacts_raw(), fetched_at=FETCHED_AT
    )
    assert snapshot.status == "succeeded" and snapshot.facts > 0
    # Direction 1: the filing pipeline's restatement-target query must not
    # see ANY companyfacts fact, even though the snapshot was published
    # before the cutoff for the same entity.
    prior = _prior_canonical_facts(
        corpus_conn,
        entity_id=ENTITY_ID,
        published_before=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert prior == {}, "companyfacts documents must be excluded from restatement targets"
    filing = ingest_filing(
        corpus_conn,
        storage,
        entity_id=ENTITY_ID,
        accession="0009999999-26-000010",
        source_url="https://example.invalid/synthetic_10q.htm",
        raw=fixture_bytes("synthetic_10q.html"),
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        form="10-Q",
    )
    assert filing.status == "succeeded" and filing.facts > 0
    filing_restates = corpus_conn.execute(
        "SELECT count(*) FROM financial_facts WHERE document_version_id = %s"
        " AND restates IS NOT NULL",
        (filing.document_version_id,),
    ).fetchone()
    assert filing_restates is not None and filing_restates[0] == 0
    # Direction 2: a companyfacts snapshot fetched AFTER the filing records
    # no restatement linkage either (normalization never consults priors).
    later = ingest_company_facts(
        corpus_conn,
        storage,
        cik=CIK,
        raw=companyfacts_raw(),
        fetched_at=datetime(2026, 6, 15, tzinfo=UTC),
    )
    assert later.status == "succeeded"
    snapshot_restates = corpus_conn.execute(
        "SELECT count(*) FROM financial_facts WHERE document_version_id = %s"
        " AND restates IS NOT NULL",
        (later.document_version_id,),
    ).fetchone()
    assert snapshot_restates is not None and snapshot_restates[0] == 0


@requires_db
def test_non_finite_payload_quarantines(corpus_conn: psycopg.Connection) -> None:
    raw = (
        b'{"cik": 9999999, "facts": {"us-gaap": {"Assets": {"units":'
        b' {"USD": [{"end": "2025-12-31", "val": NaN, "accn": "a"}]}}}}}'
    )
    outcome = ingest_company_facts(
        corpus_conn, MockStorageProvider(), cik=CIK, raw=raw, fetched_at=FETCHED_AT
    )
    assert outcome.status == "quarantined"
    assert outcome.reason_code == "NONFINITE_FACT_VALUE"
    row = corpus_conn.execute("SELECT reason_code FROM ingestion_quarantine").fetchone()
    assert row is not None and row[0] == "NONFINITE_FACT_VALUE"
    versions = corpus_conn.execute("SELECT count(*) FROM document_versions").fetchone()
    assert versions is not None and versions[0] == 0


@requires_db
def test_consumer_fails_job_when_client_lacks_capability(
    corpus_conn: psycopg.Connection,
) -> None:
    """Mirror of the unknown-kind pattern: a bound SecClient without the
    company_facts capability fails the job instead of crashing the worker."""
    queue.enqueue(
        corpus_conn,
        kind=JOB_KIND_SEC_COMPANY_FACTS,
        payload={"cik": CIK},
        queue="ingestion",
        max_attempts=1,
    )
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        PlainSecClient(),
        queue_name="ingestion",
        max_iterations=3,
    )
    assert completed == 0
    row = corpus_conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert "company_facts capability" in row[1]["error"]["message"]
    documents = corpus_conn.execute("SELECT count(*) FROM documents").fetchone()
    assert documents is not None and documents[0] == 0


@requires_db
def test_handler_payload_validation_fails_closed(corpus_conn: psycopg.Connection) -> None:
    with pytest.raises(ValueError, match="missing cik"):
        handle_sec_company_facts(
            corpus_conn, MockStorageProvider(), FixtureCompanyFactsClient(), {}
        )


@requires_db
def test_enqueue_idempotency_is_day_scoped(corpus_conn: psycopg.Connection) -> None:
    first = enqueue_company_facts(corpus_conn, cik=CIK, snapshot_day=date(2026, 5, 20))
    replay = enqueue_company_facts(corpus_conn, cik="CIK0009999999", snapshot_day=date(2026, 5, 20))
    next_day = enqueue_company_facts(corpus_conn, cik=CIK, snapshot_day=date(2026, 5, 21))
    assert first == replay
    assert next_day != first
    keys = {row[0] for row in corpus_conn.execute("SELECT idempotency_key FROM jobs").fetchall()}
    assert keys == {
        "sec-companyfacts|0009999999|2026-05-20",
        "sec-companyfacts|0009999999|2026-05-21",
    }


def test_ingest_errors_are_quarantineable() -> None:
    """MALFORMED_JSON is a first-class member of the closed reason-code set."""
    err = IngestError("MALFORMED_JSON", "diagnostic")
    assert err.reason_code == "MALFORMED_JSON"
