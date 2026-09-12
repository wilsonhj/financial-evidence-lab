"""Run projections and scope-bound continuation over durable rows."""

import uuid

import psycopg


def test_equal_timestamp_pages_and_backward_navigation(
    extraction_client, extraction_tenant, seeded_runs
):
    tenant = extraction_tenant
    path = f"/v1/workspaces/{tenant['workspace']}/extraction-runs"
    for order, expected in [("asc", seeded_runs), ("desc", list(reversed(seeded_runs)))]:
        params = {"limit": 2, "order": order}
        seen = []
        previous = None
        while True:
            response = extraction_client.get(path, params=params, headers=tenant["headers"])
            assert response.status_code == 200, response.text
            page = response.json()
            assert set(page) == {"items", "limit", "next_cursor", "previous_cursor"}
            assert page["limit"] == 2
            rows = [row["id"] for row in page["items"]]
            seen.extend(rows)
            if previous is not None:
                back = extraction_client.get(
                    path, params={"cursor": page["previous_cursor"]}, headers=tenant["headers"]
                )
                assert [row["id"] for row in back.json()["items"]] == previous
            previous = rows
            if not page["next_cursor"]:
                break
            params = {"cursor": page["next_cursor"]}
        assert seen == expected


def test_representation_etag_tracks_worker_usage_without_version_increment(
    extraction_client, extraction_tenant, seeded_runs, extraction_url
):
    path = f"/v1/extraction-runs/{seeded_runs[0]}"
    first = extraction_client.get(path, headers=extraction_tenant["headers"])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["usage"] == {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": "0.000000",
    }
    assert body["cancel_requested_at"] is None
    assert "policy_id" not in body and "input_manifest" not in body and "org_id" not in body
    repeated = extraction_client.get(path, headers=extraction_tenant["headers"])
    assert repeated.headers["ETag"] == first.headers["ETag"]
    with psycopg.connect(extraction_url) as conn:
        conn.execute("UPDATE extraction_runs SET calls_used=1 WHERE id=%s", (seeded_runs[0],))
    changed = extraction_client.get(path, headers=extraction_tenant["headers"])
    assert changed.json()["version"] == body["version"]
    assert changed.json()["usage"]["calls"] == 1
    assert changed.headers["ETag"] != first.headers["ETag"]


def test_run_reads_hide_foreign_rows_and_reject_cursor_scope_swap(
    extraction_client, extraction_tenant, seeded_runs, extraction_url
):
    tenant = extraction_tenant
    path = f"/v1/workspaces/{tenant['workspace']}/extraction-runs"
    page = extraction_client.get(path, params={"limit": 2}, headers=tenant["headers"])
    assert page.status_code == 200, page.text
    other = str(uuid.uuid4())
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of)"
            " VALUES (%s,%s,'other',%s,'USD','FY','2026-06-30Z')",
            (other, tenant["org"], tenant["entity"]),
        )
    swapped = extraction_client.get(
        f"/v1/workspaces/{other}/extraction-runs",
        params={"cursor": page.json()["next_cursor"]},
        headers=tenant["headers"],
    )
    assert swapped.status_code == 422
    assert (
        extraction_client.get(
            f"/v1/extraction-runs/{uuid.uuid4()}", headers=tenant["headers"]
        ).status_code
        == 404
    )
