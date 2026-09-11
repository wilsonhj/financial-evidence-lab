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


def test_reader_rejects_large_fact_metadata_before_transferring_payload(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE financial_facts SET label=repeat('x', 33*1024*1024) WHERE id=%s",
            (ids["target_fact"],),
        )
    from app import reader

    original = reader._fact_body
    seen = []

    def tracked(row, **kwargs):
        seen.append(row["id"])
        return original(row, **kwargs)

    monkeypatch.setattr(reader, "_fact_body", tracked)
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        params={"include_siblings": "false"},
        headers=_headers(org_fixture),
    )
    assert response.status_code == 413
    assert seen == [], "oversized database payload must be rejected before fact materialization"


@pytest.mark.parametrize("collection", ["spans", "facts"])
def test_last_allowed_evidence_row_is_included_and_overflow_fails_before_hashing(
    client, org_fixture, db_url, tmp_path, monkeypatch, collection
):
    from app import reader

    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)

    def insert(conn, count):
        if collection == "spans":
            conn.execute(
                "INSERT INTO source_spans (id, document_version_id, section_id, page, "
                "start_char, end_char, text_hash) SELECT gen_random_uuid(), "
                "document_version_id, section_id, page, start_char, end_char, text_hash "
                "FROM source_spans CROSS JOIN generate_series(1, %s) WHERE id=%s",
                (count, ids["target_span"]),
            )
        else:
            conn.execute(
                "INSERT INTO financial_facts (id, entity_id, document_version_id, "
                "concept, value, unit, period_type, period_start, period_end, "
                "source_span_id, fact_key) SELECT gen_random_uuid(), entity_id, "
                "document_version_id, concept, value, unit, period_type, period_start, "
                "period_end, source_span_id, gen_random_uuid()::text FROM "
                "financial_facts CROSS JOIN generate_series(1, %s) WHERE id=%s",
                (count, ids["target_fact"]),
            )

    with psycopg.connect(db_url) as conn:
        insert(conn, 9999)
    url = f"/v1/documents/{ids['target_id']}/reader"
    response = client.get(url, params={"include_siblings": "false"}, headers=_headers(org_fixture))
    assert response.status_code == 200
    assert len(response.json()["document"][collection]) == 10000
    with psycopg.connect(db_url) as conn:
        insert(conn, 1)
    called = []
    original = reader._span_body

    def tracked(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(reader, "_span_body", tracked)
    response = client.get(url, params={"include_siblings": "false"}, headers=_headers(org_fixture))
    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit_kind"] == collection
    assert not called


def test_unicode_overlapping_sections_are_bounded_before_assembly(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        vid = _insert_version(
            conn,
            tmp_path,
            document_id=ids["target_id"],
            text="😀" * 500000,
            parser_version="unicode",
            normalizer_version="n",
            created_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
        conn.execute(
            "INSERT INTO sections (id, document_version_id, heading, heading_path, ord, "
            "start_char, end_char) SELECT gen_random_uuid(), %s, 's', '{}', n, 0, 500000"
            " FROM generate_series(0, 19) n",
            (vid,),
        )
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        params={"include_siblings": "false"},
        headers=_headers(org_fixture),
    )
    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit_kind"] == "section_bytes"


def test_overlapping_span_hash_work_is_bounded(client, org_fixture, db_url, tmp_path, monkeypatch):
    from tests.test_reader_api import _insert_evidence

    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    text = "x" * 100000
    with psycopg.connect(db_url) as conn:
        vid = _insert_version(
            conn,
            tmp_path,
            document_id=ids["target_id"],
            text=text,
            parser_version="overlap",
            normalizer_version="n",
            created_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
        ev = _insert_evidence(
            conn,
            entity_id=ids["entity_id"],
            version_id=vid,
            text=text,
            span_start=0,
            span_end=len(text),
        )
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) SELECT gen_random_uuid(), document_version_id, "
            "section_id, start_char, end_char, text_hash FROM source_spans CROSS JOIN "
            "generate_series(1, 400) WHERE id=%s",
            (ev["span_id"],),
        )
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        params={"include_siblings": "false"},
        headers=_headers(org_fixture),
    )
    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit_kind"] == "verification_bytes"


def test_foreign_version_and_pin_mismatch_retain_uniform_not_found(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    import uuid

    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    pin = str(uuid.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO corpus_versions (id,label,status) VALUES (%s,%s,'superseded')", (pin, pin)
        )
        conn.execute(
            "INSERT INTO corpus_version_documents (corpus_version_id, "
            "document_version_id) VALUES (%s, %s)",
            (pin, ids["old_version"]),
        )
    for params in [
        {"document_version_id": ids["sibling_version"]},
        {"document_version_id": str(uuid.uuid4())},
        {"document_version_id": ids["selected_version"], "corpus_version_id": pin},
        {"document_version_id": ids["selected_version"], "as_of": "2020-01-01T00:00:00Z"},
    ]:
        response = client.get(
            f"/v1/documents/{ids['target_id']}/reader", params=params, headers=_headers(org_fixture)
        )
        assert response.status_code == 404
        body = response.json()["error"]
        body.pop("request_id")
        assert body == {"code": "NOT_FOUND", "message": "Document not found.", "details": {}}


def test_large_synthetic_filing_fits_all_document_row_caps(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    """2 MiB canonical, 2k sections and 10k spans/facts fit without truncation."""
    from tests.test_reader_api import _hash

    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        version = _insert_version(
            conn,
            tmp_path,
            document_id=ids["target_id"],
            text="x" * (2000 * 1024),
            parser_version="large",
            normalizer_version="n",
            created_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
        conn.execute(
            "INSERT INTO sections (id, document_version_id, heading, heading_path, ord, "
            "start_char, end_char) SELECT gen_random_uuid(), %s, 'Item 7', '{}', n, "
            "n*1024, (n+1)*1024 FROM generate_series(0, 1999) n",
            (version,),
        )
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) SELECT gen_random_uuid(), document_version_id, id, "
            "start_char+n*100, start_char+n*100+100, %s FROM sections CROSS JOIN "
            "generate_series(0, 4) n WHERE document_version_id=%s",
            (_hash("x" * 100), version),
        )
        conn.execute(
            "INSERT INTO financial_facts (id, entity_id, document_version_id, concept, "
            "value, unit, period_type, period_instant, source_span_id, fact_key) SELECT "
            "gen_random_uuid(), %s, document_version_id, 'revenue', '100', 'USD', "
            "'instant', '2026-01-01', id, id::text FROM source_spans WHERE "
            "document_version_id=%s",
            (ids["entity_id"], version),
        )
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        params={"include_siblings": "false"},
        headers=_headers(org_fixture),
    )
    assert response.status_code == 200
    body = response.json()["document"]
    assert len(body["sections"]) == 2000
    assert len(body["spans"]) == len(body["facts"]) == 10000
    assert body["sections"][-1]["end_char"] == 2000 * 1024
    assert body["spans"][-1]["span"]["text_hash"] == _hash("x" * 100)
    assert len(response.content) <= 32 * 1024 * 1024


def test_oversized_sibling_identifies_its_own_original_metadata(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    with psycopg.connect(db_url) as conn:
        key = conn.execute(
            "SELECT canonical_text_key FROM document_versions WHERE id=%s",
            (ids["sibling_version"],),
        ).fetchone()[0]
    (tmp_path / key).write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    url = f"/v1/documents/{ids['target_id']}/reader"
    target = client.get(url, params={"include_siblings": "false"}, headers=_headers(org_fixture))
    assert target.status_code == 200
    response = client.get(url, params={"sibling_limit": 1}, headers=_headers(org_fixture))
    assert response.status_code == 413
    details = response.json()["error"]["details"]
    assert details["resource"] == ids["sibling_id"]
    assert details["metadata_url"] == f"/v1/documents/{ids['sibling_id']}"
    assert ids["target_id"] not in details["metadata_url"]


@pytest.mark.parametrize(
    "as_of", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00", "2026-06-01T00:00:00"]
)
def test_reader_cutoff_outside_utc_range_is_422(
    client, org_fixture, db_url, tmp_path, monkeypatch, as_of
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    response = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        params={"include_siblings": "false", "as_of": as_of},
        headers=_headers(org_fixture),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_equivalent_offset_cutoffs_preserve_page_and_reader_evidence(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    for url, params in [
        (f"/v1/entities/{ids['entity_id']}/documents", {"limit": 1}),
        ("/v1/document-versions/resolve", {"document_version_id": ids["selected_version"]}),
        (f"/v1/documents/{ids['target_id']}/reader", {"sibling_limit": 1}),
    ]:
        responses = [
            client.get(url, params={**params, "as_of": cutoff}, headers=_headers(org_fixture))
            for cutoff in ["2026-05-07T00:00:00Z", "2026-05-06T17:00:00-07:00"]
        ]
        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json() == responses[1].json()
        assert responses[0].headers.get("X-FEL-Next-Cursor") == responses[1].headers.get(
            "X-FEL-Next-Cursor"
        )


def test_sibling_cursor_accepts_equivalent_uppercase_tenant_uuid(
    client, org_fixture, db_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    ids = _seed_reader(db_url, tmp_path)
    headers = _headers((org_fixture[0].upper(), org_fixture[1]))
    url = f"/v1/documents/{ids['target_id']}/reader"
    first = client.get(url, params={"sibling_limit": 1}, headers=headers)
    assert first.status_code == 200
    cursor = first.json()["sibling_page"]["next_cursor"]
    assert cursor
    second = client.get(url, params={"sibling_cursor": cursor}, headers=headers)
    assert second.status_code == 200
    assert first.json()["siblings"][0]["meta"]["id"] != second.json()["siblings"][0]["meta"]["id"]
