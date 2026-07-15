"""ADR-0005 composite evidence-reader integration tests.

These tests use a real disposable PostgreSQL database with migrations applied.
Canonical text is stored in a temporary content-addressed directory so the API
must verify the same immutable bytes used by ingestion.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from tests.conftest import requires_db

pytestmark = requires_db


def _headers(org: tuple[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_mock_token(org[0], org[1], 'viewer')}"}


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _put_text(root: Path, key: str, text: str) -> None:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _insert_document(
    conn: psycopg.Connection[Any],
    *,
    entity_id: str,
    published_at: datetime,
    form: str = "10-Q",
) -> str:
    document_id = str(uuid.uuid4())
    accession = f"reader-{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO documents
            (id, entity_id, accession, form, source_url, content_hash,
             storage_key, published_at, filed_at, period_start, period_end)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '2026-01-01', '2026-03-31')
        """,
        (
            document_id,
            entity_id,
            accession,
            form,
            f"https://example.invalid/{accession}.htm",
            _hash(accession),
            f"raw/sha256/{uuid.uuid4().hex}",
            published_at,
            published_at,
        ),
    )
    return document_id


def _insert_version(
    conn: psycopg.Connection[Any],
    storage_root: Path,
    *,
    document_id: str,
    text: str,
    parser_version: str,
    normalizer_version: str,
    created_at: datetime,
    status: str = "parsed",
) -> str:
    version_id = str(uuid.uuid4())
    key = f"text/sha256/{hashlib.sha256(text.encode()).hexdigest()}-{version_id}"
    _put_text(storage_root, key, text)
    conn.execute(
        """
        INSERT INTO document_versions
            (id, document_id, parser_version, normalizer_version, status,
             canonical_text_key, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            version_id,
            document_id,
            parser_version,
            normalizer_version,
            status,
            key,
            created_at,
        ),
    )
    return version_id


def _insert_evidence(
    conn: psycopg.Connection[Any],
    *,
    entity_id: str,
    version_id: str,
    text: str,
    section_start: int = 0,
    section_end: int | None = None,
    span_start: int | None = None,
    span_end: int | None = None,
    concept: str = "us-gaap:Revenue",
    value: str = "100.00",
) -> dict[str, str]:
    end = len(text) if section_end is None else section_end
    start = section_start + 5 if span_start is None else span_start
    stop = min(end, start + 12) if span_end is None else span_end
    ids = {name: str(uuid.uuid4()) for name in ("section_id", "span_id", "fact_id")}
    conn.execute(
        """
        INSERT INTO sections
            (id, document_version_id, heading, heading_path, ord, start_char, end_char)
        VALUES (%s, %s, 'Management discussion', %s, 0, %s, %s)
        """,
        (ids["section_id"], version_id, ["Part II", "Item 7"], section_start, end),
    )
    conn.execute(
        """
        INSERT INTO source_spans
            (id, document_version_id, section_id, page, start_char, end_char, text_hash)
        VALUES (%s, %s, %s, 7, %s, %s, %s)
        """,
        (
            ids["span_id"],
            version_id,
            ids["section_id"],
            start,
            stop,
            _hash(text[start:stop]),
        ),
    )
    conn.execute(
        """
        INSERT INTO financial_facts
            (id, entity_id, document_version_id, concept, label, value, unit,
             scale, period_type, period_start, period_end, dimensions,
             source_span_id, reported_or_derived, confidence, fact_key)
        VALUES (%s, %s, %s, %s, 'Revenue', %s, 'USD', 0, 'duration',
                '2026-01-01', '2026-03-31', '{"segment":"Cloud"}'::jsonb,
                %s, 'reported', 1, %s)
        """,
        (
            ids["fact_id"],
            entity_id,
            version_id,
            concept,
            value,
            ids["span_id"],
            f"{concept}|{uuid.uuid4()}",
        ),
    )
    return ids


def _seed_reader(db_url: str, storage_root: Path) -> dict[str, str | datetime]:
    entity_id = str(uuid.uuid4())
    published = datetime(2026, 5, 5, 16, 30, tzinfo=UTC)
    target_text = "HEADER" + "x" * 200 + "Revenue grew by 20 percent." + "z" * 40
    sibling_text = "AMENDMENT Revenue was restated to 99.00." + "q" * 50
    ids: dict[str, str | datetime] = {
        "entity_id": entity_id,
        "published": published,
        "target_text": target_text,
    }
    with psycopg.connect(db_url) as conn:
        target_id = _insert_document(conn, entity_id=entity_id, published_at=published)
        sibling_id = _insert_document(
            conn,
            entity_id=entity_id,
            published_at=published + timedelta(days=1),
            form="10-Q/A",
        )
        late_id = _insert_document(
            conn,
            entity_id=entity_id,
            published_at=published + timedelta(days=30),
            form="8-K",
        )
        old_version = _insert_version(
            conn,
            storage_root,
            document_id=target_id,
            text="old parsed text",
            parser_version="z-old",
            normalizer_version="z-old",
            created_at=published,
        )
        selected_version = _insert_version(
            conn,
            storage_root,
            document_id=target_id,
            text=target_text,
            parser_version="a-selected",
            normalizer_version="a-selected",
            created_at=published + timedelta(hours=1),
        )
        # A still-newer quarantined version must never be selected.
        _insert_version(
            conn,
            storage_root,
            document_id=target_id,
            text="quarantined text",
            parser_version="zz-quarantine",
            normalizer_version="zz-quarantine",
            created_at=published + timedelta(hours=2),
            status="quarantined",
        )
        sibling_version = _insert_version(
            conn,
            storage_root,
            document_id=sibling_id,
            text=sibling_text,
            parser_version="p1",
            normalizer_version="n1",
            created_at=published + timedelta(days=1, hours=1),
        )
        late_version = _insert_version(
            conn,
            storage_root,
            document_id=late_id,
            text="future text",
            parser_version="p1",
            normalizer_version="n1",
            created_at=published + timedelta(days=30, hours=1),
        )
        evidence = _insert_evidence(
            conn,
            entity_id=entity_id,
            version_id=selected_version,
            text=target_text,
            section_start=100,
            section_end=len(target_text),
            span_start=206,
            span_end=232,
        )
        sibling_evidence = _insert_evidence(
            conn,
            entity_id=entity_id,
            version_id=sibling_version,
            text=sibling_text,
            span_start=10,
            span_end=37,
            value="99.00",
        )
        _insert_evidence(
            conn,
            entity_id=entity_id,
            version_id=late_version,
            text="future text",
            span_start=0,
            span_end=6,
        )
        conn.execute(
            "UPDATE financial_facts SET restates = %s WHERE id = %s",
            (evidence["fact_id"], sibling_evidence["fact_id"]),
        )
        ids.update(
            {
                "target_id": target_id,
                "sibling_id": sibling_id,
                "late_id": late_id,
                "old_version": old_version,
                "selected_version": selected_version,
                "sibling_version": sibling_version,
                "target_span": evidence["span_id"],
                "target_fact": evidence["fact_id"],
                "sibling_fact": sibling_evidence["fact_id"],
            }
        )
    return ids


def test_latest_reader_is_cutoff_safe_version_consistent_and_hash_verified(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    cutoff = ids["published"] + timedelta(days=1)  # type: ignore[operator]
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=_headers(org_fixture),
        params={"as_of": cutoff.isoformat()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body["as_of"]) == cutoff
    assert body["corpus_version_id"] is None
    assert body["selection_policy"] == "latest_parsed"
    assert body["document"]["meta"]["id"] == ids["target_id"]
    assert body["document"]["document_version_id"] == ids["selected_version"]
    assert body["document"]["meta"]["id"] != body["document"]["document_version_id"]
    assert [item["meta"]["id"] for item in body["siblings"]] == [ids["sibling_id"]]

    section = body["document"]["sections"][0]
    target_text = ids["target_text"]
    assert section["start_char"] == 100
    assert section["content"] == target_text[100:]  # type: ignore[index]
    span_record = body["document"]["spans"][0]
    span = span_record["span"]
    assert span_record["id"] == ids["target_span"]
    assert span["document_version_id"] == ids["selected_version"]
    assert span["start_char"] > 100
    assert span["text_hash"] == _hash(target_text[span["start_char"] : span["end_char"]])  # type: ignore[index]
    fact = body["document"]["facts"][0]
    assert fact["document_version_id"] == ids["selected_version"]
    assert fact["fact"]["source_span_id"] == span_record["id"]
    assert fact["fact"]["value"] == "100.00"
    assert body["siblings"][0]["facts"][0]["restates"] == ids["target_fact"]

    blocks = [body["document"], *body["siblings"]]
    returned_fact_ids = {item["id"] for block in blocks for item in block["facts"]}
    for block in blocks:
        returned_span_ids = {item["id"] for item in block["spans"]}
        for item in block["facts"]:
            assert item["document_version_id"] == block["document_version_id"]
            assert item["fact"]["source_span_id"] in returned_span_ids
            for link in ("duplicate_of", "restates"):
                if link in item:
                    assert item[link] in returned_fact_ids


def test_cutoff_boundary_and_hidden_target_match_missing_404(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    at_boundary = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=_headers(org_fixture),
        params={"as_of": ids["published"].isoformat()},  # type: ignore[union-attr]
    )
    assert at_boundary.status_code == 200
    assert at_boundary.json()["siblings"] == []

    cutoff = ids["published"] - timedelta(microseconds=1)  # type: ignore[operator]
    hidden = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=_headers(org_fixture),
        params={"as_of": cutoff.isoformat()},
    )
    missing = client.get(
        f"/v1/documents/{uuid.uuid4()}/reader",
        headers=_headers(org_fixture),
        params={"as_of": cutoff.isoformat()},
    )
    assert hidden.status_code == missing.status_code == 404
    for response in (hidden, missing):
        error = response.json()["error"]
        assert {key: error[key] for key in ("code", "message", "details")} == {
            "code": "NOT_FOUND",
            "message": "Document not found.",
            "details": {},
        }


def test_reader_rejects_naive_cutoff_and_requires_membership(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
) -> None:
    document_id = str(uuid.uuid4())
    unauthenticated = client.get(f"/v1/documents/{document_id}/reader")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "UNAUTHENTICATED"

    naive = client.get(
        f"/v1/documents/{document_id}/reader",
        headers=_headers(org_fixture),
        params={"as_of": "2026-07-01T00:00:00"},
    )
    assert naive.status_code == 422
    assert naive.json()["error"]["code"] == "VALIDATION_ERROR"

    forged = make_mock_token(str(uuid.uuid4()), str(uuid.uuid4()), "viewer")
    forbidden = client.get(
        f"/v1/documents/{document_id}/reader",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "NOT_A_MEMBER"


def test_corpus_pin_selects_exact_version_and_rejects_unknown_or_draft(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    pinned_id, draft_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'superseded')",
            (pinned_id, f"reader-pin-{pinned_id}"),
        )
        conn.execute(
            "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id)"
            " VALUES (%s, %s), (%s, %s)",
            (pinned_id, ids["old_version"], pinned_id, ids["sibling_version"]),
        )
        conn.execute(
            "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'draft')",
            (draft_id, f"reader-draft-{draft_id}"),
        )

    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=_headers(org_fixture),
        params={
            "as_of": "2026-07-01T00:00:00Z",
            "corpus_version_id": pinned_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["selection_policy"] == "corpus_pinned"
    assert response.json()["corpus_version_id"] == pinned_id
    assert response.json()["document"]["document_version_id"] == ids["old_version"]

    for invalid_pin in (str(uuid.uuid4()), draft_id):
        rejected = client.get(
            f"/v1/documents/{ids['target_id']}/reader",
            headers=_headers(org_fixture),
            params={"corpus_version_id": invalid_pin},
        )
        assert rejected.status_code == 404
        assert rejected.json()["error"]["details"] == {"resource": "corpus_version"}


def test_corpus_pin_fails_closed_on_multiple_versions_for_one_document(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    corpus_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'superseded')",
            (corpus_id, f"reader-corrupt-{corpus_id}"),
        )
        conn.execute(
            "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id)"
            " VALUES (%s, %s), (%s, %s)",
            (corpus_id, ids["old_version"], corpus_id, ids["selected_version"]),
        )
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=_headers(org_fixture),
        params={"corpus_version_id": corpus_id},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_reader_fails_closed_when_persisted_span_hash_is_corrupt(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE source_spans SET text_hash = %s WHERE id = %s",
            ("sha256:" + "0" * 64, ids["target_span"]),
        )
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=_headers(org_fixture),
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"


def test_latest_version_total_order_uses_c_collation_tiebreakers(
    client: TestClient,
    org_fixture: tuple[str, str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    entity_id = str(uuid.uuid4())
    created_at = datetime(2026, 5, 1, tzinfo=UTC)
    text = "0123456789 deterministic tie"
    with psycopg.connect(db_url) as conn:
        document_id = _insert_document(conn, entity_id=entity_id, published_at=created_at)
        lower = _insert_version(
            conn,
            tmp_path,
            document_id=document_id,
            text="lower version",
            parser_version="parser-A",
            normalizer_version="normalizer-z",
            created_at=created_at,
        )
        selected = _insert_version(
            conn,
            tmp_path,
            document_id=document_id,
            text=text,
            parser_version="parser-z",
            normalizer_version="normalizer-A",
            created_at=created_at,
        )
        _insert_evidence(
            conn,
            entity_id=entity_id,
            version_id=selected,
            text=text,
            span_start=2,
            span_end=10,
        )
    response = client.get(f"/v1/documents/{document_id}/reader", headers=_headers(org_fixture))
    assert response.status_code == 200, response.text
    assert response.json()["document"]["document_version_id"] == selected
    assert response.json()["document"]["document_version_id"] != lower
