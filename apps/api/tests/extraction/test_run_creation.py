"""Atomic creation binds current policy, frozen source bytes and the durable job."""

import uuid

import psycopg
import pytest
from psycopg.rows import dict_row


def _request(tenant, source):
    return {
        "entity_id": tenant["entity"],
        "as_of": "2026-12-31T00:00:00Z",
        "modes": ["kpi"],
        "source_span_ids": [source["span"]],
        "corpus_version_id": source["corpus"],
    }


def _create(client, tenant, source, **changes):
    return client.post(
        f"/v1/workspaces/{tenant['workspace']}/extraction-runs",
        json={**_request(tenant, source), **changes},
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )


def test_create_pins_latest_policy_cutoff_sources_and_exact_job(
    extraction_client, extraction_tenant, extraction_url, source_fixture
):
    tenant, source = extraction_tenant, source_fixture
    policy2 = str(uuid.uuid4())
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO extraction_policies(id,org_id,version,created_by,max_calls,supersedes_id)"
            " VALUES (%s,%s,2,%s,4,%s)",
            (policy2, tenant["org"], tenant["user"], tenant["policy"]),
        )
    response = _create(extraction_client, tenant, source)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["as_of"].startswith("2026-06-30") and body["limits"]["max_calls"] == 4
    assert body["corpus_version_id"] == source["corpus"] and body["provider"] == "mock"
    assert (
        "policy_id" not in body
        and "input_manifest" not in body
        and source["text"] not in response.text
    )
    with psycopg.connect(extraction_url, row_factory=dict_row) as conn:
        run = conn.execute("SELECT * FROM extraction_runs WHERE id=%s", (body["id"],)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE id=%s", (body["id"],)).fetchone()
        events = conn.execute(
            "SELECT event_type FROM extraction_run_events WHERE run_id=%s", (body["id"],)
        ).fetchall()
    assert str(run["policy_id"]) == policy2
    assert run["input_manifest"]["conflict_occurrence_policy"] == "run/v1"
    assert source["text"] not in str(run["input_manifest"])
    assert (
        str(job["org_id"]) == tenant["org"]
        and job["kind"] == "extraction_run"
        and job["queue"] == "extraction"
    )
    assert job["payload"]["request"]["policy_id"] == policy2
    assert job["payload"]["request"]["input_hash"] == run["input_hash"]
    assert job["payload"]["evidence"] == [
        {
            "source_span_id": source["span"],
            "document_version_id": source["version"],
            "text": source["text"],
            "text_hash": source["hash"],
            "published_at": "2026-02-01T00:00:00+00:00",
        }
    ]
    assert events == [{"event_type": "run_queued"}]


@pytest.mark.parametrize("failure", ["hash", "missing", "cutoff", "entity", "budget", "mock_unset"])
def test_rejected_create_has_no_partial_side_effects(
    extraction_client, extraction_tenant, extraction_url, source_fixture, monkeypatch, failure
):
    tenant, source = extraction_tenant, source_fixture
    changes = {}
    if failure == "hash":
        source["path"].write_text("tampered evidence")
    elif failure == "missing":
        changes["source_span_ids"] = [source["span"], str(uuid.uuid4())]
    elif failure == "cutoff":
        changes["as_of"] = "2025-01-01T00:00:00Z"
    elif failure == "entity":
        changes["entity_id"] = str(uuid.uuid4())
    elif failure == "budget":
        with psycopg.connect(extraction_url) as conn:
            conn.execute(
                "INSERT INTO extraction_policies(id,org_id,version,created_by,max_calls) "
                "VALUES (%s,%s,2,%s,2)",
                (uuid.uuid4(), tenant["org"], tenant["user"]),
            )
        changes["limits"] = {"max_calls": 3}
    else:
        monkeypatch.delenv("FEL_ALLOW_MOCK_LLM")
    response = _create(extraction_client, tenant, source, **changes)
    assert response.status_code in {404, 422, 503}, response.text
    with psycopg.connect(extraction_url) as conn:
        for table in (
            "extraction_runs",
            "jobs",
            "extraction_run_events",
            "audit_events",
            "idempotency_keys",
        ):
            assert (
                conn.execute(
                    f"SELECT count(*) FROM {table} WHERE org_id=%s", (tenant["org"],)
                ).fetchone()[0]
                == 0
            )
