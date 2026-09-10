"""ADR-0021 target-first reader limits with real stored evidence."""

from datetime import UTC, datetime

import psycopg
import pytest

from tests.conftest import requires_db
from tests.test_reader_api import _headers, _insert_document, _insert_version, _seed_reader

pytestmark = requires_db


def test_target_only_and_related_pages_pin_the_selected_target(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    url = f"/v1/documents/{ids['target_id']}/reader"
    response = client.get(url, params={"include_siblings": "false"}, headers=_headers(org_fixture))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["siblings"] == []
    assert body["sibling_page"]["scope"] == "excluded"
    assert body["sibling_page"]["complete"] is False
    version = body["document"]["document_version_id"]
    with psycopg.connect(db_url) as conn:
        _insert_version(
            conn,
            tmp_path,
            document_id=ids["target_id"],
            text="new parse",
            parser_version="new",
            normalizer_version="new",
            created_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
    first = client.get(
        url,
        params={"sibling_limit": 1, "as_of": body["as_of"], "document_version_id": version},
        headers=_headers(org_fixture),
    )
    assert first.status_code == 200, first.text
    assert first.json()["document"]["document_version_id"] == version
    assert len(first.json()["siblings"]) == 1
    cursor = first.json()["sibling_page"]["next_cursor"]
    second = client.get(
        url,
        params={"sibling_cursor": cursor, "as_of": body["as_of"], "document_version_id": version},
        headers=_headers(org_fixture),
    )
    assert second.status_code == 200, second.text
    assert second.json()["document"]["document_version_id"] == version
    assert second.json()["siblings"][0]["meta"]["id"] != first.json()["siblings"][0]["meta"]["id"]


def test_legacy_sibling_overflow_does_not_block_target_only(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        for _ in range(21):
            did = _insert_document(conn, entity_id=ids["entity_id"], published_at=ids["published"])
            _insert_version(
                conn,
                tmp_path,
                document_id=did,
                text="evidence",
                parser_version="p",
                normalizer_version="n",
                created_at=ids["published"],
            )
    url = f"/v1/documents/{ids['target_id']}/reader"
    response = client.get(url, headers=_headers(org_fixture))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAGINATION_REQUIRED"
    response = client.get(url, headers=_headers(org_fixture), params={"include_siblings": "false"})
    assert response.status_code == 200


def test_canonical_object_read_is_bounded(tmp_path, monkeypatch):
    from app import reader

    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    (tmp_path / "large").write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    with pytest.raises(Exception) as err:
        reader._read_canonical_text("large")
    assert err.value.status_code == 413
    assert err.value.detail["code"] == "READER_TOO_LARGE"


def test_sections_cap_rejects_before_building_strings(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO sections (id,document_version_id,heading,heading_path,"
            "ord,start_char,end_char) SELECT gen_random_uuid(),%s,'section','{}',n,0,1"
            " FROM generate_series(1,2000) n",
            (ids["selected_version"],),
        )
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        params={"include_siblings": "false"},
        headers=_headers(org_fixture),
    )
    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit_kind"] == "sections"
