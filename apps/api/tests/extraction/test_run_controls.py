"""Run control preserves history and binds cancellation to the actual queued job."""

import uuid

import psycopg
import pytest

from tests.extraction.test_proposal_reads import _insert, _payload
from tests.extraction.test_run_creation import _create


def test_cancel_replay_preserves_original_response_after_worker_terminalization(
    extraction_client, extraction_tenant, extraction_url, source_fixture
):
    tenant = extraction_tenant
    created = _create(extraction_client, tenant, source_fixture)
    path = "/v1/extraction-runs/" + created.json()["id"]
    headers = {
        **tenant["headers"],
        "If-Match": created.headers["ETag"],
        "Idempotency-Key": str(uuid.uuid4()),
    }
    cancelled = extraction_client.delete(path, headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert (
        cancelled.json()["status"] == "queued"
        and cancelled.json()["cancel_requested_at"] is not None
    )
    with psycopg.connect(extraction_url) as conn:
        markers = conn.execute(
            "SELECT r.cancel_requested_at,j.cancel_requested_at FROM extraction_runs r "
            "JOIN jobs j ON j.id=r.id WHERE r.id=%s",
            (created.json()["id"],),
        ).fetchone()
        assert markers[0] == markers[1]
        conn.execute(
            "UPDATE extraction_runs SET status='cancelled',finished_at=now() WHERE id=%s",
            (created.json()["id"],),
        )
    replay = extraction_client.delete(path, headers=headers)
    assert replay.json() == cancelled.json() and replay.headers["ETag"] == cancelled.headers["ETag"]
    current = extraction_client.get(path, headers=tenant["headers"])
    fresh = extraction_client.delete(
        path,
        headers={
            **headers,
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": current.headers["ETag"],
        },
    )
    assert fresh.status_code == 409


def test_cancel_stale_usage_etag_does_not_touch_job(
    extraction_client, extraction_tenant, extraction_url, source_fixture
):
    tenant = extraction_tenant
    created = _create(extraction_client, tenant, source_fixture)
    run_id = created.json()["id"]
    with psycopg.connect(extraction_url) as conn:
        conn.execute("UPDATE extraction_runs SET calls_used=1 WHERE id=%s", (run_id,))
    response = extraction_client.delete(
        "/v1/extraction-runs/" + run_id,
        headers={
            **tenant["headers"],
            "If-Match": created.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 412, response.text
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute("SELECT cancel_requested_at FROM jobs WHERE id=%s", (run_id,)).fetchone()[
                0
            ]
            is None
        )


def test_waiting_review_cancel_preserves_proposals_and_appends_terminal_event(
    extraction_client, extraction_tenant, extraction_url, source_fixture
):
    tenant = extraction_tenant
    created = _create(extraction_client, tenant, source_fixture)
    run_id = created.json()["id"]
    proposal = _insert(extraction_url, tenant, run_id, _payload(tenant["entity"]))
    with psycopg.connect(extraction_url) as conn:
        conn.execute("UPDATE extraction_runs SET status='running' WHERE id=%s", (run_id,))
        conn.execute("UPDATE extraction_runs SET status='waiting_review' WHERE id=%s", (run_id,))
    current = extraction_client.get("/v1/extraction-runs/" + run_id, headers=tenant["headers"])
    response = extraction_client.delete(
        "/v1/extraction-runs/" + run_id,
        headers={
            **tenant["headers"],
            "If-Match": current.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    with psycopg.connect(extraction_url) as conn:
        assert conn.execute(
            "SELECT state,version FROM extraction_proposals WHERE id=%s", (proposal,)
        ).fetchone() == ("proposed", 1)
        assert (
            conn.execute(
                "SELECT event_type FROM extraction_run_events "
                "WHERE run_id=%s ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()[0]
            == "run_cancelled"
        )


@pytest.mark.parametrize("cutoff,expected", [("2026-05-01Z", 202), ("2025-01-01Z", 422)])
def test_rerun_retains_sources_and_parent_with_current_cutoff(
    extraction_client, extraction_tenant, extraction_url, source_fixture, cutoff, expected
):
    tenant = extraction_tenant
    parent = _create(extraction_client, tenant, source_fixture).json()
    with psycopg.connect(extraction_url) as conn:
        conn.execute("UPDATE workspaces SET as_of=%s WHERE id=%s", (cutoff, tenant["workspace"]))
    response = extraction_client.post(
        f"/v1/extraction-runs/{parent['id']}/rerun",
        json={"reason": "Repeat extraction"},
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == expected, response.text
    assert (
        extraction_client.get(
            "/v1/extraction-runs/" + parent["id"], headers=tenant["headers"]
        ).json()
        == parent
    )
    if expected == 202:
        child = response.json()
        assert child["id"] != parent["id"] and child["parent_run_id"] == parent["id"]
        assert child["corpus_version_id"] == parent["corpus_version_id"]
        assert child["as_of"].startswith("2026-05-01")
        with psycopg.connect(extraction_url) as conn:
            manifest = conn.execute(
                "SELECT input_manifest FROM extraction_runs WHERE id=%s", (child["id"],)
            ).fetchone()[0]
        assert (
            manifest["source_span_ids"] == [source_fixture["span"]]
            and manifest["conflict_occurrence_policy"] == "run/v1"
        )
    else:
        with psycopg.connect(extraction_url) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM extraction_runs WHERE org_id=%s", (tenant["org"],)
                ).fetchone()[0]
                == 1
            )
