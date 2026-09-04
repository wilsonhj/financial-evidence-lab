"""#191: cost ceilings, usage metering, and the bounded query-snapshot run list.

These reuse the retrieval suite's seeding fixtures, so they run against the
same isolated ``*_retrieval`` sibling database and skip without
TEST_DATABASE_URL.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_DATABASE_URL, ensure_retrieval_database, requires_db
from tests.test_retrieval_api import _headers, _seed_indexed_workspace

pytestmark = requires_db


@pytest.fixture()
def db_url(monkeypatch: pytest.MonkeyPatch) -> str:
    assert TEST_DATABASE_URL is not None
    url = ensure_retrieval_database(TEST_DATABASE_URL)
    monkeypatch.setenv("FEL_DATABASE_URL", url)
    return url


@pytest.fixture()
def org(db_url: str) -> tuple[str, str]:
    org_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO organizations (id, name) VALUES (%s, %s)", (org_id, org_id[:8]))
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (org_id, user_id),
        )
    return org_id, user_id


@pytest.fixture()
def seeded(db_url: str, org: tuple[str, str]) -> dict[str, str]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        return _seed_indexed_workspace(conn, org[0])


def _create(client: TestClient, org: tuple[str, str], workspace_id: str) -> Any:
    return client.post(
        f"/v1/workspaces/{workspace_id}/queries",
        json={"question": "What was revenue in fiscal 2025?"},
        headers={**_headers(*org), "Idempotency-Key": str(uuid.uuid4())},
    )


def _book_spend(db_url: str, org: tuple[str, str], amount: str) -> None:
    """Book prior spend for this org/user as the superuser (bypassing RLS)."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO usage_events (org_id, user_id, kind, cost_usd)"
            " VALUES (%s, %s, 'seed', %s)",
            (org[0], org[1], amount),
        )


def _metered(db_url: str, org: tuple[str, str]) -> list[tuple[str, Decimal]]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT kind, cost_usd FROM usage_events WHERE org_id = %s AND kind <> 'seed'"
            " ORDER BY id",
            (org[0],),
        ).fetchall()
    return [(str(row[0]), Decimal(row[1])) for row in rows]


def test_normal_run_is_metered_without_a_cost_warning(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    """Under both ceilings: no warning header, and the run's reported provider
    usage lands in usage_events and on the trace as the same number."""
    resp = _create(client, org, seeded["workspace_id"])
    assert resp.status_code == 202, resp.text
    assert "X-FEL-Cost-Warning" not in resp.headers

    rows = _metered(db_url, org)
    assert [kind for kind, _ in rows] == ["research_query"]
    cost = rows[0][1]
    assert cost > 0, "the pinned mock providers report tokens, so a run is never free"

    trace = client.get(f"/v1/retrieval-runs/{resp.json()['run_id']}", headers=_headers(*org)).json()
    assert Decimal(trace["cost_usd"]) == cost


def test_soft_limit_warns_but_still_runs(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    """A crossed soft limit warns; it never downgrades the run or blocks it."""
    _book_spend(db_url, org, "10.50")  # over the USD 10 user daily soft limit
    resp = _create(client, org, seeded["workspace_id"])
    assert resp.status_code == 202, resp.text
    assert resp.headers["X-FEL-Cost-Warning"] == "user daily soft limit exceeded"

    trace = client.get(f"/v1/retrieval-runs/{resp.json()['run_id']}", headers=_headers(*org)).json()
    assert trace["status"] in {"succeeded", "abstained"}
    assert [kind for kind, _ in _metered(db_url, org)] == ["research_query"]


def test_hard_limit_stops_new_billable_work(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    """A crossed hard limit refuses the run outright: no run row, no metering."""
    first = _create(client, org, seeded["workspace_id"])
    assert first.status_code == 202, first.text
    query_id = first.json()["query_id"]

    _book_spend(db_url, org, "24.90")  # 24.90 + the USD 0.25 query ceiling > 25

    refused = _create(client, org, seeded["workspace_id"])
    assert refused.status_code == 402, refused.text
    error = refused.json()["error"]
    assert error["code"] == "COST_LIMIT_EXCEEDED"
    assert error["details"]["limit_usd"] == "25"
    assert error["request_id"]

    # A rerun re-executes the whole pipeline, so it carries the same ceiling.
    rerun = client.post(
        f"/v1/queries/{query_id}/reruns",
        headers={**_headers(*org), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert rerun.status_code == 402, rerun.text
    assert rerun.json()["error"]["code"] == "COST_LIMIT_EXCEEDED"

    # Only the pre-limit run was ever metered, and no extra run was persisted.
    assert [kind for kind, _ in _metered(db_url, org)] == ["research_query"]
    snapshot = client.get(f"/v1/queries/{query_id}", headers=_headers(*org)).json()
    assert len(snapshot["runs"]) == 1


def test_query_snapshot_run_list_is_bounded(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    assert created.status_code == 202, created.text
    query_id = created.json()["query_id"]
    rerun = client.post(
        f"/v1/queries/{query_id}/reruns",
        headers={**_headers(*org), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert rerun.status_code == 202, rerun.text

    default_limit = client.get(f"/v1/queries/{query_id}", headers=_headers(*org))
    assert len(default_limit.json()["runs"]) == 2

    bounded = client.get(f"/v1/queries/{query_id}", params={"limit": 1}, headers=_headers(*org))
    assert len(bounded.json()["runs"]) == 1
    assert bounded.json()["runs"][0]["run_id"] == rerun.json()["run_id"]

    for out_of_range in (0, 201):
        rejected = client.get(
            f"/v1/queries/{query_id}",
            params={"limit": out_of_range},
            headers=_headers(*org),
        )
        assert rejected.status_code == 422, out_of_range
        assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"


def test_metering_fault_does_not_leave_a_succeeded_unbilled_run(
    client: TestClient,
    org: tuple[str, str],
    seeded: dict[str, str],
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A usage insert failure must not 500 a durable success, nor skip billing
    forever on replay. Metering shares the pipeline transaction, so the run
    lands ``failed`` and usage stays empty."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("usage insert failed")

    monkeypatch.setattr("app.retrieval.record_usage", _boom)
    resp = _create(client, org, seeded["workspace_id"])
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    trace = client.get(f"/v1/retrieval-runs/{run_id}", headers=_headers(*org))
    assert trace.status_code == 200, trace.text
    assert trace.json()["status"] == "failed"
    assert _metered(db_url, org) == []
