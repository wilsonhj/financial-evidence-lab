"""Read-only corpus evidence endpoints: point-in-time document listing,
document metadata, and stable source spans (frozen openapi v0.1.0)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from tests.conftest import requires_db

pytestmark = requires_db

TEXT_HASH = "sha256:" + "ab12" * 16


def _headers(org: tuple[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_mock_token(org[0], org[1], 'viewer')}"}


def _seed_corpus(db_url: str) -> dict[str, str]:
    """Insert a document/version/section/span as the worker service role."""
    ids = {
        "entity_id": str(uuid.uuid4()),
        "early_doc": str(uuid.uuid4()),
        "late_doc": str(uuid.uuid4()),
        "version_id": str(uuid.uuid4()),
        "late_version_id": str(uuid.uuid4()),
        "section_id": str(uuid.uuid4()),
        "span_id": str(uuid.uuid4()),
    }
    suffix = uuid.uuid4().hex[:8]
    with psycopg.connect(db_url) as conn:
        conn.execute(
            """
            INSERT INTO documents (id, entity_id, accession, form, source_url,
                content_hash, storage_key, published_at, filed_at,
                period_start, period_end)
            VALUES (%s, %s, %s, '10-Q', 'https://example.invalid/early.htm',
                    %s, 'raw/sha256/aa', '2026-05-05T16:30:00Z',
                    '2026-05-05T16:00:00Z', '2026-01-01', '2026-03-31')
            """,
            (ids["early_doc"], ids["entity_id"], f"acc-early-{suffix}", TEXT_HASH),
        )
        conn.execute(
            """
            INSERT INTO documents (id, entity_id, accession, form, source_url,
                content_hash, storage_key, published_at)
            VALUES (%s, %s, %s, '8-K', 'https://example.invalid/late.htm',
                    %s, 'raw/sha256/bb', '2026-06-20T12:00:00Z')
            """,
            (ids["late_doc"], ids["entity_id"], f"acc-late-{suffix}", TEXT_HASH),
        )
        conn.execute(
            "INSERT INTO document_versions (id, document_id, parser_version,"
            " normalizer_version, canonical_text_key)"
            " VALUES (%s, %s, 'p1', 'n1', 'text/sha256/aa')",
            (ids["version_id"], ids["early_doc"]),
        )
        conn.execute(
            "INSERT INTO document_versions (id, document_id, parser_version,"
            " normalizer_version, canonical_text_key)"
            " VALUES (%s, %s, 'p1', 'n1', 'text/sha256/bb')",
            (ids["late_version_id"], ids["late_doc"]),
        )
        conn.execute(
            "INSERT INTO sections (id, document_version_id, heading, heading_path,"
            " ord, start_char, end_char) VALUES (%s, %s, 'Item 1', %s, 0, 0, 100)",
            (ids["section_id"], ids["version_id"], ["Item 1"]),
        )
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, page,"
            " start_char, end_char, text_hash) VALUES (%s, %s, %s, 42, 10, 60, %s)",
            (ids["span_id"], ids["version_id"], ids["section_id"], TEXT_HASH),
        )
    return ids


def test_point_in_time_document_listing(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    ids = _seed_corpus(db_url)
    headers = _headers(org_fixture)

    # A cutoff between the two publications hides the later document.
    early_only = client.get(
        f"/v1/entities/{ids['entity_id']}/documents",
        headers=headers,
        params={"as_of": "2026-06-01T00:00:00Z"},
    )
    assert early_only.status_code == 200
    body = early_only.json()
    assert [doc["id"] for doc in body] == [ids["early_doc"]]
    doc = body[0]
    assert doc["entity_id"] == ids["entity_id"]
    assert doc["form"] == "10-Q"
    assert re.match(r"^sha256:[0-9a-f]{64}$", doc["content_hash"])
    assert doc["published_at"].startswith("2026-05-05")
    assert doc["filed_at"].startswith("2026-05-05")
    assert doc["period_start"] == "2026-01-01"
    assert doc["period_end"] == "2026-03-31"
    assert "ingested_at" in doc and "valid_from" in doc

    # The exact publication instant is included (<=, not <).
    at_publication = client.get(
        f"/v1/entities/{ids['entity_id']}/documents",
        headers=headers,
        params={"as_of": "2026-05-05T16:30:00Z"},
    )
    assert [d["id"] for d in at_publication.json()] == [ids["early_doc"]]

    # No cutoff returns everything, ordered by publication time.
    everything = client.get(f"/v1/entities/{ids['entity_id']}/documents", headers=headers)
    assert [d["id"] for d in everything.json()] == [ids["early_doc"], ids["late_doc"]]

    # A pre-publication cutoff sees nothing.
    nothing = client.get(
        f"/v1/entities/{ids['entity_id']}/documents",
        headers=headers,
        params={"as_of": "2026-01-01T00:00:00Z"},
    )
    assert nothing.json() == []


def test_naive_as_of_is_rejected_with_envelope(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    response = client.get(
        f"/v1/entities/{uuid.uuid4()}/documents",
        headers=_headers(org_fixture),
        params={"as_of": "2026-06-01T00:00:00"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_document_and_404_envelope(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    ids = _seed_corpus(db_url)
    headers = _headers(org_fixture)
    found = client.get(f"/v1/documents/{ids['early_doc']}", headers=headers)
    assert found.status_code == 200
    assert found.json()["id"] == ids["early_doc"]
    missing = client.get(f"/v1/documents/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    body = missing.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"].startswith("req-")


def test_get_source_span_contract_shape(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    ids = _seed_corpus(db_url)
    response = client.get(f"/v1/source-spans/{ids['span_id']}", headers=_headers(org_fixture))
    assert response.status_code == 200
    span = response.json()
    assert span == {
        "document_version_id": ids["version_id"],
        "section_id": ids["section_id"],
        "page": 42,
        "start_char": 10,
        "end_char": 60,
        "text_hash": TEXT_HASH,
    }
    missing = client.get(f"/v1/source-spans/{uuid.uuid4()}", headers=_headers(org_fixture))
    assert missing.status_code == 404


def test_corpus_reads_require_authentication(client: TestClient, db_url: str) -> None:
    response = client.get(f"/v1/entities/{uuid.uuid4()}/documents")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_corpus_reads_reject_non_members(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    forged = make_mock_token(str(uuid.uuid4()), str(uuid.uuid4()), "owner")
    response = client.get(
        f"/v1/entities/{uuid.uuid4()}/documents",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_MEMBER"


def test_quarantined_documents_are_invisible_via_corpus_reads(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    """Finding 3: a document without a successfully parsed version (its every
    ingestion attempt quarantined) must not appear in the listing and must
    404 on the by-id endpoint; boundary-inclusive as_of stays intact."""
    entity_id = str(uuid.uuid4())
    parsed_doc, unparsed_doc, quarantined_doc = (str(uuid.uuid4()) for _ in range(3))
    suffix = uuid.uuid4().hex[:8]
    with psycopg.connect(db_url) as conn:
        for doc_id, accession in (
            (parsed_doc, f"acc-parsed-{suffix}"),
            (unparsed_doc, f"acc-unparsed-{suffix}"),
            (quarantined_doc, f"acc-quarantined-{suffix}"),
        ):
            conn.execute(
                """
                INSERT INTO documents (id, entity_id, accession, form, source_url,
                    content_hash, storage_key, published_at)
                VALUES (%s, %s, %s, '10-Q', 'https://example.invalid/q.htm',
                        %s, 'raw/sha256/cc', '2026-05-05T16:30:00Z')
                """,
                (doc_id, entity_id, accession, TEXT_HASH),
            )
        conn.execute(
            "INSERT INTO document_versions (id, document_id, parser_version,"
            " normalizer_version, status, canonical_text_key)"
            " VALUES (%s, %s, 'p1', 'n1', 'parsed', 'text/sha256/cc')",
            (str(uuid.uuid4()), parsed_doc),
        )
        # quarantined_doc has only a quarantined version; unparsed_doc has none.
        conn.execute(
            "INSERT INTO document_versions (id, document_id, parser_version,"
            " normalizer_version, status, canonical_text_key)"
            " VALUES (%s, %s, 'p1', 'n1', 'quarantined', 'text/sha256/cc')",
            (str(uuid.uuid4()), quarantined_doc),
        )
    headers = _headers(org_fixture)
    listing = client.get(f"/v1/entities/{entity_id}/documents", headers=headers)
    assert [doc["id"] for doc in listing.json()] == [parsed_doc]
    # Boundary-inclusive as_of still serves the parsed document.
    at_publication = client.get(
        f"/v1/entities/{entity_id}/documents",
        headers=headers,
        params={"as_of": "2026-05-05T16:30:00Z"},
    )
    assert [doc["id"] for doc in at_publication.json()] == [parsed_doc]
    assert client.get(f"/v1/documents/{parsed_doc}", headers=headers).status_code == 200
    for invisible in (unparsed_doc, quarantined_doc):
        response = client.get(f"/v1/documents/{invisible}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_fel_app_has_no_select_grant_on_ingestion_internals(db_url: str) -> None:
    """Finding 13 (ADR-0004): ingestion_quarantine and ingestion_runs are
    operational internals — the fel_app API role must NOT hold SELECT on
    them, while the corpus evidence tables stay readable."""
    with psycopg.connect(db_url) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL ROLE fel_app")
            for evidence_table in ("documents", "document_versions", "financial_facts"):
                conn.execute(f"SELECT 1 FROM {evidence_table} LIMIT 1")  # noqa: S608
        for internal_table in ("ingestion_quarantine", "ingestion_runs"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("SET LOCAL ROLE fel_app")
                    conn.execute(f"SELECT 1 FROM {internal_table} LIMIT 1")  # noqa: S608


def test_timestamps_are_timezone_aware(
    client: TestClient, org_fixture: tuple[str, str], db_url: str
) -> None:
    ids = _seed_corpus(db_url)
    doc = client.get(f"/v1/documents/{ids['early_doc']}", headers=_headers(org_fixture)).json()
    published = datetime.fromisoformat(doc["published_at"])
    assert published.tzinfo is not None
    assert published.astimezone(UTC) == datetime(2026, 5, 5, 16, 30, tzinfo=UTC)
