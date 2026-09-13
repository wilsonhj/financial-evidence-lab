"""Bounded actual-ID history and legacy metadata redaction."""

import psycopg
import pytest
from psycopg.types.json import Jsonb


@pytest.mark.parametrize("resume", ["-1", "1.5", "9007199254740992", "01", "true"])
def test_resume_rejects_unsafe_or_noninteger_ids(
    extraction_client, extraction_tenant, waiting_review_fixture, resume
):
    response = extraction_client.get(
        f"/v1/extraction-runs/{waiting_review_fixture['run']}/events",
        headers={**extraction_tenant["headers"], "Last-Event-ID": resume},
    )
    assert response.status_code == 422, response.text


def test_event_history_traverses_actual_ids_and_omits_legacy_control_content(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    with psycopg.connect(extraction_url) as conn:
        row = conn.execute(
            "INSERT INTO extraction_run_events(org_id,run_id,event_type,payload) "
            "VALUES (%s,%s,'heartbeat',%s) RETURNING id",
            (
                tenant["org"],
                fixture["run"],
                Jsonb(
                    {
                        "worker_private": "do not expose",
                        "count": 3,
                        "stage_output": {"secret": "hidden"},
                    }
                ),
            ),
        ).fetchone()
    path = f"/v1/extraction-runs/{fixture['run']}/event-history"
    first = extraction_client.get(path + "?limit=2", headers=tenant["headers"])
    assert first.status_code == 200, first.text
    collected = list(first.json()["items"])
    current = first.json()
    while current["next_cursor"]:
        page = extraction_client.get(
            path, params={"cursor": current["next_cursor"]}, headers=tenant["headers"]
        )
        assert page.status_code == 200, page.text
        current = page.json()
        collected.extend(current["items"])
    assert [item["id"] for item in collected] == sorted({item["id"] for item in collected})
    assert collected[-1]["id"] == row[0] and collected[-1]["payload"] == {"count": 3}
    backward = extraction_client.get(
        path, params={"cursor": current["previous_cursor"]}, headers=tenant["headers"]
    )
    assert backward.status_code == 200, backward.text
    assert backward.json()["items"][-1]["id"] < current["items"][0]["id"]
