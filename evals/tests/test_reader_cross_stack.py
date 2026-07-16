"""Issue #96 READER-CROSS-STACK — mock-first ADR-0005 verification.

Default path needs no credentials. Optional stack path seeds a disposable
Postgres (via ``qa_database_url`` / ``TEST_DATABASE_URL``) and exercises the
real FastAPI composite reader. Product defects in ``apps/**`` are blockers,
not patches in this package.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from harness import reader_cross_stack as rcs

# ---------------------------------------------------------------------------
# Mock-first (always runs)
# ---------------------------------------------------------------------------


def test_dataset_is_mock_first_and_scenario_manifest_is_complete() -> None:
    scenarios = rcs.load_scenarios()
    assert scenarios["policy"] == "mock-first"
    ids = {item["id"] for item in scenarios["scenarios"]}
    assert {
        "latest_parsed_ok",
        "corpus_pinned_ok",
        "integrity_corrupt_hash",
        "integrity_out_of_range",
        "amendment_chain",
        "error_surfaces",
    } <= ids
    readme = (rcs.DATASET_DIR / "README.md").read_text()
    assert "Mock-first" in readme
    assert "no credentials" in readme.lower() or "Mock-first policy" in readme


def test_document_id_differs_from_selected_version_id() -> None:
    body = rcs.load_json("latest_parsed_ok.json")
    rcs.assert_document_id_differs_from_version(body)
    assert body["document"]["meta"]["id"] != body["document"]["document_version_id"]
    for sibling in body["siblings"]:
        assert sibling["meta"]["id"] != sibling["document_version_id"]


def test_pinned_and_unpinned_selection_match_adr_0005() -> None:
    unpinned = rcs.load_json("latest_parsed_ok.json")
    pinned = rcs.load_json("corpus_pinned_ok.json")
    rcs.assert_selection_policy(unpinned)
    rcs.assert_selection_policy(pinned)
    assert unpinned["corpus_version_id"] is None
    assert unpinned["selection_policy"] == "latest_parsed"
    assert pinned["corpus_version_id"] is not None
    assert pinned["selection_policy"] == "corpus_pinned"


def test_cutoff_scope_rejects_future_siblings_in_fixture() -> None:
    body = rcs.load_json("latest_parsed_ok.json")
    rcs.assert_cutoff_scope(body)
    # Exact-cutoff visibility: published_at <= as_of for every returned doc.
    cutoff = datetime.fromisoformat(body["as_of"].replace("Z", "+00:00"))
    assert (
        datetime.fromisoformat(body["document"]["meta"]["published_at"].replace("Z", "+00:00"))
        <= cutoff
    )
    # A synthetic future sibling must fail the invariant checker.
    future = {
        **body,
        "siblings": [
            {
                **body["siblings"][0],
                "meta": {
                    **body["siblings"][0]["meta"],
                    "published_at": "2099-01-01T00:00:00Z",
                },
            }
        ],
    }
    with pytest.raises(rcs.ReaderCrossStackError, match="sibling"):
        rcs.assert_cutoff_scope(future)


def test_non_first_section_citation_hash_verifies_exact_quote() -> None:
    body = rcs.load_json("latest_parsed_ok.json")
    quote = rcs.non_first_section_verified_quote(body)
    assert "Total revenue for fiscal 2025" in quote
    result = rcs.verify_span_integrity(body["document"]["sections"], body["document"]["spans"])
    assert result.failures == []
    assert len(result.verified) >= 1


def test_corrupt_hash_and_out_of_range_produce_integrity_alert_without_quote() -> None:
    for name in ("integrity_corrupt_hash.json", "integrity_out_of_range.json"):
        body = rcs.load_json(name)
        corrupt_span_id = body["document"]["spans"][0]["id"]
        result = rcs.verify_span_integrity(body["document"]["sections"], body["document"]["spans"])
        assert result.failures, f"{name} must fail integrity"
        failed_ids = {failure.span_id for failure in result.failures}
        verified_ids = {record["id"] for record in result.verified}
        assert corrupt_span_id in failed_ids
        # Failed spans never appear among verified quotes.
        assert failed_ids.isdisjoint(verified_ids)
        assert corrupt_span_id not in verified_ids
        assert result.failures[0].reason in {
            "text_hash_mismatch",
            "offsets_out_of_range",
            "section_range_mismatch",
            "unknown_section",
        }


def test_facts_resolve_to_returned_spans_of_selected_version() -> None:
    body = rcs.load_json("latest_parsed_ok.json")
    rcs.assert_facts_resolve_same_version_spans(body)


def test_multiple_amendments_resolve_to_terminal_authoritative_filing() -> None:
    payload = rcs.load_json("amendment_chain_documents.json")
    documents = payload["documents"]
    terminal = rcs.terminal_authoritative_id(documents)
    assert terminal == "33333333-3333-4333-8333-333333333333"
    links = rcs.link_amendments(documents)
    early = rcs.amendment_status_for(documents[0]["id"], links)
    mid = rcs.amendment_status_for(documents[1]["id"], links)
    assert early.kind == "superseded"
    assert early.by_document_id == terminal
    assert mid.kind == "superseded"
    assert mid.by_document_id == terminal


def test_401_403_5xx_never_surface_as_404() -> None:
    envelopes = rcs.load_json("error_envelopes.json")
    failures = rcs.assert_auth_errors_are_not_404(envelopes)
    kinds = {failure.kind for failure in failures}
    assert "not_found" not in kinds
    assert "authentication" in kinds
    assert "forbidden" in kinds
    assert "unavailable" in kinds


def test_http_mode_cannot_fall_back_to_fixtures_when_stack_available() -> None:
    rcs.assert_http_mode_no_fixture_fallback()


def test_repeated_mock_request_selects_identical_versions_and_scope() -> None:
    body = rcs.load_json("latest_parsed_ok.json")
    first = rcs.assert_reader_response_invariants
    # Pure function of fixture bytes: two loads are identical.
    again = rcs.load_json("latest_parsed_ok.json")
    assert body == again
    first(body)
    first(again)
    assert body["document"]["document_version_id"] == again["document"]["document_version_id"]
    assert body["as_of"] == again["as_of"]
    assert [s["meta"]["id"] for s in body["siblings"]] == [
        s["meta"]["id"] for s in again["siblings"]
    ]


# ---------------------------------------------------------------------------
# Optional stack path — real FastAPI reader (skip without TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _seed_stack_corpus(db_url: str, storage_root: Path) -> dict[str, Any]:
    """Minimal synthetic corpus for ADR-0005 stack assertions (evals-owned)."""
    import psycopg

    entity_id = str(uuid.uuid4())
    published = datetime(2026, 5, 5, 16, 30, tzinfo=UTC)
    target_text = "HEADER" + "x" * 200 + "Revenue grew by 20 percent." + "z" * 40
    sibling_text = "AMENDMENT Revenue was restated to 99.00." + "q" * 50
    ids: dict[str, Any] = {
        "entity_id": entity_id,
        "published": published,
        "target_text": target_text,
    }

    def put(key: str, text: str) -> None:
        path = storage_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    with psycopg.connect(db_url) as conn:
        target_id = str(uuid.uuid4())
        sibling_id = str(uuid.uuid4())
        late_id = str(uuid.uuid4())
        for document_id, form, when, accession_suffix in (
            (target_id, "10-Q", published, "t"),
            (sibling_id, "10-Q/A", published + timedelta(days=1), "s"),
            (late_id, "8-K", published + timedelta(days=30), "l"),
        ):
            accession = f"xstack-{accession_suffix}-{uuid.uuid4().hex[:8]}"
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
                    when,
                    when,
                ),
            )

        def insert_version(
            document_id: str,
            text: str,
            parser_version: str,
            normalizer_version: str,
            created_at: datetime,
            status: str = "parsed",
        ) -> str:
            version_id = str(uuid.uuid4())
            key = f"text/sha256/{hashlib.sha256(text.encode()).hexdigest()}-{version_id}"
            put(key, text)
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

        old_version = insert_version(target_id, "old parsed text", "z-old", "z-old", published)
        selected_version = insert_version(
            target_id,
            target_text,
            "a-selected",
            "a-selected",
            published + timedelta(hours=1),
        )
        sibling_version = insert_version(
            sibling_id,
            sibling_text,
            "p1",
            "n1",
            published + timedelta(days=1, hours=1),
        )
        late_version = insert_version(
            late_id,
            "future text",
            "p1",
            "n1",
            published + timedelta(days=30, hours=1),
        )

        def insert_evidence(
            version_id: str,
            text: str,
            *,
            section_start: int = 0,
            span_start: int | None = None,
            span_end: int | None = None,
            value: str = "100.00",
        ) -> dict[str, str]:
            end = len(text)
            start = section_start + 5 if span_start is None else span_start
            stop = min(end, start + 12) if span_end is None else span_end
            section_id, span_id, fact_id = (str(uuid.uuid4()) for _ in range(3))
            conn.execute(
                """
                INSERT INTO sections
                    (id, document_version_id, heading, heading_path, ord, start_char, end_char)
                VALUES (%s, %s, 'MD&A', %s, 0, %s, %s)
                """,
                (section_id, version_id, ["Part II", "Item 7"], section_start, end),
            )
            conn.execute(
                """
                INSERT INTO source_spans
                    (id, document_version_id, section_id, page, start_char, end_char, text_hash)
                VALUES (%s, %s, %s, 7, %s, %s, %s)
                """,
                (span_id, version_id, section_id, start, stop, _hash(text[start:stop])),
            )
            concept = "us-gaap:Revenue"
            conn.execute(
                """
                INSERT INTO financial_facts
                    (id, entity_id, document_version_id, concept, label, value, unit,
                     scale, period_type, period_start, period_end, dimensions,
                     source_span_id, reported_or_derived, confidence, fact_key)
                VALUES (%s, %s, %s, %s, 'Revenue', %s, 'USD', 0, 'duration',
                        '2026-01-01', '2026-03-31', '{}'::jsonb,
                        %s, 'reported', 1, %s)
                """,
                (
                    fact_id,
                    entity_id,
                    version_id,
                    concept,
                    value,
                    span_id,
                    f"{concept}|{uuid.uuid4()}",
                ),
            )
            return {"section_id": section_id, "span_id": span_id, "fact_id": fact_id}

        target_evidence = insert_evidence(
            selected_version,
            target_text,
            section_start=100,
            span_start=206,
            span_end=232,
        )
        sibling_evidence = insert_evidence(
            sibling_version, sibling_text, span_start=10, span_end=37, value="99.00"
        )
        insert_evidence(late_version, "future text", span_start=0, span_end=6)
        conn.execute(
            "UPDATE financial_facts SET restates = %s WHERE id = %s",
            (target_evidence["fact_id"], sibling_evidence["fact_id"]),
        )
        ids.update(
            {
                "target_id": target_id,
                "sibling_id": sibling_id,
                "late_id": late_id,
                "old_version": old_version,
                "selected_version": selected_version,
                "sibling_version": sibling_version,
                "target_span": target_evidence["span_id"],
                "target_fact": target_evidence["fact_id"],
            }
        )
    return ids


def _auth_headers(org: tuple[str, str]) -> dict[str, str]:
    from app.auth import make_mock_token

    return {"Authorization": f"Bearer {make_mock_token(org[0], org[1], 'viewer')}"}


@pytest.fixture()
def stack_reader(qa_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Disposable DB + FastAPI TestClient + seeded synthetic corpus."""
    import psycopg
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("FEL_DATABASE_URL", qa_database_url)
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))

    org_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(qa_database_url) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, %s)",
            (org_id, f"org-{org_id[:8]}"),
        )
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (org_id, user_id),
        )
    ids = _seed_stack_corpus(qa_database_url, tmp_path)
    client = TestClient(app)
    return client, (org_id, user_id), ids


def test_stack_latest_reader_doc_ne_version_cutoff_pin_and_determinism(
    stack_reader: tuple[Any, tuple[str, str], dict[str, Any]],
) -> None:
    client, org, ids = stack_reader
    headers = _auth_headers(org)
    cutoff = ids["published"] + timedelta(days=1)
    params = {"as_of": cutoff.isoformat()}
    first = client.get(f"/v1/documents/{ids['target_id']}/reader", headers=headers, params=params)
    second = client.get(f"/v1/documents/{ids['target_id']}/reader", headers=headers, params=params)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body = first.json()
    assert body == second.json()
    rcs.assert_reader_response_invariants(body)
    assert body["document"]["meta"]["id"] != body["document"]["document_version_id"]
    assert body["document"]["document_version_id"] == ids["selected_version"]
    assert body["selection_policy"] == "latest_parsed"
    assert [item["meta"]["id"] for item in body["siblings"]] == [ids["sibling_id"]]
    assert ids["late_id"] not in {item["meta"]["id"] for item in body["siblings"]}

    # Exact cutoff: target visible, amendment sibling not yet published.
    at_boundary = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=headers,
        params={"as_of": ids["published"].isoformat()},
    )
    assert at_boundary.status_code == 200
    assert at_boundary.json()["siblings"] == []

    # Future direct URL is indistinguishable from missing (ADR-0005).
    hidden = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=headers,
        params={"as_of": (ids["published"] - timedelta(microseconds=1)).isoformat()},
    )
    missing = client.get(
        f"/v1/documents/{uuid.uuid4()}/reader",
        headers=headers,
        params={"as_of": cutoff.isoformat()},
    )
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["code"] == missing.json()["error"]["code"] == "NOT_FOUND"


def test_stack_corpus_pin_and_auth_surfaces(
    stack_reader: tuple[Any, tuple[str, str], dict[str, Any]],
    qa_database_url: str,
) -> None:
    client, org, ids = stack_reader
    headers = _auth_headers(org)
    pin_id = str(uuid.uuid4())
    import psycopg

    with psycopg.connect(qa_database_url) as conn:
        conn.execute(
            "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'superseded')",
            (pin_id, f"xstack-pin-{pin_id}"),
        )
        conn.execute(
            "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id)"
            " VALUES (%s, %s), (%s, %s)",
            (pin_id, ids["old_version"], pin_id, ids["sibling_version"]),
        )

    pinned = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers=headers,
        params={"as_of": "2026-07-01T00:00:00Z", "corpus_version_id": pin_id},
    )
    assert pinned.status_code == 200, pinned.text
    body = pinned.json()
    assert body["selection_policy"] == "corpus_pinned"
    assert body["corpus_version_id"] == pin_id
    assert body["document"]["document_version_id"] == ids["old_version"]
    assert body["document"]["meta"]["id"] != body["document"]["document_version_id"]

    unauthenticated = client.get(f"/v1/documents/{ids['target_id']}/reader")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "UNAUTHENTICATED"
    assert unauthenticated.status_code != 404

    from app.auth import make_mock_token

    forged = make_mock_token(str(uuid.uuid4()), str(uuid.uuid4()), "viewer")
    forbidden = client.get(
        f"/v1/documents/{ids['target_id']}/reader",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "NOT_A_MEMBER"
    assert forbidden.status_code != 404


def test_stack_corrupt_span_hash_returns_integrity_error_not_404(
    stack_reader: tuple[Any, tuple[str, str], dict[str, Any]],
    qa_database_url: str,
) -> None:
    client, org, ids = stack_reader
    import psycopg

    with psycopg.connect(qa_database_url) as conn:
        conn.execute(
            "UPDATE source_spans SET text_hash = %s WHERE id = %s",
            ("sha256:" + "0" * 64, ids["target_span"]),
        )
    response = client.get(f"/v1/documents/{ids['target_id']}/reader", headers=_auth_headers(org))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTEGRITY_ERROR"
    assert response.status_code != 404
