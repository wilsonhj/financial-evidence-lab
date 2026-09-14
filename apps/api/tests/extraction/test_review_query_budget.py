"""Bulk review must not issue a database round trip for every row and field."""

from pathlib import Path
from uuid import uuid4

import psycopg

from app.auth import make_mock_token
from benchmarks.extraction_load_fixture import BulkMock, seed, state, verify
from fel_providers.mocks import MockSecClient
from fel_workers.consumer import run_worker
from fel_workers.storage import LocalDirStorageProvider, apply_worker_db_role


def test_100_item_review_has_bounded_sql_round_trips(
    extraction_client, extraction_url, tmp_path, monkeypatch
):
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", "fel_worker")
    ids = seed(extraction_url, Path(tmp_path))
    headers = {"Authorization": "Bearer " + make_mock_token(ids["org"], ids["user"], "owner")}
    created = extraction_client.post(
        f"/v1/workspaces/{ids['workspace']}/extraction-runs",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=dict(
            entity_id=ids["entity"],
            as_of="2026-07-01T00:00:00Z",
            modes=["kpi"],
            source_span_ids=[ids["span"]],
            corpus_version_id=ids["corpus"],
        ),
    )
    assert created.status_code == 202
    ids["run"] = created.json()["id"]
    # Other extraction tests deliberately leave queued jobs. Isolate only this
    # fixture job's queue so the real consumer cannot claim their fixtures.
    queue = "review-budget-" + uuid4().hex
    with psycopg.connect(extraction_url) as conn:
        conn.execute("UPDATE jobs SET queue=%s WHERE id=%s", (queue, ids["run"]))
    with psycopg.connect(extraction_url, autocommit=True) as conn:
        apply_worker_db_role(conn)
        assert (
            run_worker(
                conn,
                LocalDirStorageProvider(tmp_path),
                MockSecClient(),
                queue_name=queue,
                max_iterations=1,
                structured_llm=BulkMock(ids),
            )
            == 1
        )
    proposals = state(extraction_url, ids)["proposals"]
    with psycopg.connect(extraction_url) as conn:
        periods = {
            str(pid): payload["period"]
            for pid, payload in conn.execute(
                "SELECT id,payload FROM extraction_proposals WHERE run_id=%s", (ids["run"],)
            ).fetchall()
        }
    calls = []
    original = psycopg.Connection.execute

    def counted(conn, query, *args, **kwargs):
        calls.append(str(query))
        return original(conn, query, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(psycopg.Connection, "execute", counted)
        result = extraction_client.post(
            "/v1/extractions/review",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json=dict(
                action="accept",
                extraction_ids=[str(p["id"]) for p in proposals],
                expected_versions={str(p["id"]): p["version"] for p in proposals},
                reason="Explicit synthetic load regression",
            ),
        )
    assert result.status_code == 200, result.text
    verify(extraction_url, ids)
    for receipt, proposal in zip(result.json()["approved_versions"], proposals, strict=True):
        detail = extraction_client.get(
            f"/v1/approved-extractions/{receipt['record_id']}",
            headers=headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == receipt["etag"]
        assert detail.json()["version_id"] == receipt["version_id"]
        assert detail.json()["payload"]["period"] == periods[str(proposal["id"])]
    # This is an operation budget, not a machine-dependent latency assertion.
    # 60 permits bounded safety/provenance probes, but rejects the observed829.
    assert len(calls) <= 60, f"100-item review issued {len(calls)} SQL operations"


def test_bulk_insert_failure_rolls_back_records_versions_and_receipt(
    extraction_client, extraction_url, extraction_tenant, waiting_review_fixture, monkeypatch
):
    import pytest

    from tests.extraction.test_review_atomicity import command

    fixture = waiting_review_fixture
    headers = {**extraction_tenant["headers"], "Idempotency-Key": str(uuid4())}
    body = command(fixture["proposal"])
    original = psycopg.Connection.execute

    def fail_after_versions(conn, query, *args, **kwargs):
        result = original(conn, query, *args, **kwargs)
        if str(query).startswith("INSERT INTO approved_extraction_versions"):
            raise RuntimeError("Injected after actual version insertion")
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(psycopg.Connection, "execute", fail_after_versions)
        with pytest.raises(RuntimeError, match="Injected after actual version insertion"):
            extraction_client.post("/v1/extractions/review", headers=headers, json=body)
    with psycopg.connect(extraction_url) as conn:
        for table in (
            "approved_extraction_records",
            "approved_extraction_versions",
            "extraction_reviews",
        ):
            assert (
                conn.execute(
                    psycopg.sql.SQL("SELECT count(*) FROM {} WHERE org_id=%s").format(
                        psycopg.sql.Identifier(table)
                    ),
                    (extraction_tenant["org"],),
                ).fetchone()[0]
                == 0
            )
        assert conn.execute(
            "SELECT state,version FROM extraction_proposals WHERE id=%s",
            (fixture["proposal"],),
        ).fetchone() == ("needs_review", 1)
        assert (
            conn.execute(
                "SELECT count(*) FROM idempotency_keys WHERE org_id=%s AND key=%s",
                (extraction_tenant["org"], headers["Idempotency-Key"]),
            ).fetchone()[0]
            == 0
        )
    result = extraction_client.post("/v1/extractions/review", headers=headers, json=body)
    assert result.status_code == 200
    replay = extraction_client.post("/v1/extractions/review", headers=headers, json=body)
    assert replay.content == result.content
