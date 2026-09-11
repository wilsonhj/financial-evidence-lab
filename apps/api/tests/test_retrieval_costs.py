"""#191: cost reservations, usage metering, and complete query snapshots.

These reuse the retrieval suite's seeding fixtures, so they run against the
same isolated ``*_retrieval`` sibling database and skip without
TEST_DATABASE_URL.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import retrieval
from app.auth import TenantContext
from app.costs import lock_query_budget, spend_snapshot
from app.db import tenant_connection
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


def test_query_snapshot_keeps_every_run(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    assert created.status_code == 202, created.text
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO retrieval_runs (id, org_id, query_id, parent_run_id, mode,"
            " config_hash, embedding_provider, embedding_model, generation_provider,"
            " generation_model, planner_version)"
            " SELECT gen_random_uuid(), org_id, query_id, id, 'rerun', config_hash,"
            " embedding_provider, embedding_model, generation_provider, generation_model,"
            " planner_version FROM retrieval_runs CROSS JOIN generate_series(1, 50)"
            " WHERE id = %s",
            (created.json()["run_id"],),
        )
    snapshot = client.get(f"/v1/queries/{created.json()['query_id']}", headers=_headers(*org))
    assert snapshot.status_code == 409, snapshot.text
    assert snapshot.json()["error"]["code"] == "PAGINATION_REQUIRED"
    snapshot = client.get(
        f"/v1/queries/{created.json()['query_id']}",
        params={"limit": 200},
        headers=_headers(*org),
    )
    assert snapshot.status_code == 200, snapshot.text
    assert len(snapshot.json()["runs"]) == 51


@pytest.mark.parametrize("scope", ["user", "organization"])
def test_pending_run_reserves_budget_before_generation(
    client: TestClient,
    org: tuple[str, str],
    seeded: dict[str, str],
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
) -> None:
    # Keep the first run inside its pipeline while a second request attempts
    # admission. This must not serialize the whole pipeline under an org lock.
    _book_spend(db_url, org, "24.75" if scope == "user" else "999.75")
    if scope == "organization":
        monkeypatch.setenv("FEL_USER_DAILY_LIMIT_USD", "2000")
    started, release = Event(), Event()
    execute = retrieval._execute_pipeline

    def paused(*args: Any, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(10), "test failed to release the first pipeline"
        return execute(*args, **kwargs)

    monkeypatch.setattr(retrieval, "_execute_pipeline", paused)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_create, client, org, seeded["workspace_id"])
        try:
            assert started.wait(10), "first query never reached the pipeline"
            second = executor.submit(_create, client, org, seeded["workspace_id"])
            refused = second.result(timeout=5)
            assert refused.status_code == 402, refused.text
            assert refused.json()["error"]["code"] == "COST_LIMIT_EXCEEDED"
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 202
    assert len(_metered(db_url, org)) == 1


def test_rerun_reservation_belongs_to_the_caller_not_the_query_author(
    client: TestClient,
    org: tuple[str, str],
    seeded: dict[str, str],
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    caller = (org[0], str(uuid.uuid4()))
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'editor')",
            caller,
        )
    _book_spend(db_url, caller, "24.75")
    # Simulate a process stopping after admission commits. The queued run and
    # its reservation remain durable, even across a day/month rollover.
    monkeypatch.setattr(retrieval, "_run_pipeline_or_fail", lambda *a, **kw: None)
    rerun = client.post(
        f"/v1/queries/{created.json()['query_id']}/reruns",
        headers={**_headers(*caller), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert rerun.status_code == 202, rerun.text
    refused = _create(client, caller, seeded["workspace_id"])
    assert refused.status_code == 402, refused.text
    # The author's daily allowance is independent; organization spend is shared.
    assert _create(client, org, seeded["workspace_id"]).status_code == 202


@pytest.mark.parametrize("persistent", [False, True])
def test_metering_failure_never_leaves_an_unbilled_success(
    client: TestClient,
    org: tuple[str, str],
    seeded: dict[str, str],
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    persistent: bool,
) -> None:
    original = retrieval.record_usage
    calls = 0
    actual_cost = None

    def fail_usage(*args: Any) -> None:
        nonlocal calls, actual_cost
        calls += 1
        actual_cost = args[-1]
        if persistent or calls == 1:
            raise RuntimeError("injected metering outage")
        original(*args)

    monkeypatch.setattr(retrieval, "record_usage", fail_usage)
    headers = {**_headers(*org), "Idempotency-Key": str(uuid.uuid4())}
    url = f"/v1/workspaces/{seeded['workspace_id']}/queries"
    body = {"question": "What was revenue in fiscal 2025?"}
    with TestClient(client.app, raise_server_exceptions=False) as http:
        response = http.post(url, headers=headers, json=body)
        assert response.status_code == (500 if persistent else 202), response.text
        replay = http.post(url, headers=headers, json=body)
        assert replay.status_code == 202, replay.text
        trace = http.get(
            f"/v1/retrieval-runs/{replay.json()['run_id']}", headers=_headers(*org)
        ).json()
    assert trace["status"] == ("queued" if persistent else "failed")
    assert calls == 2  # Replay must not regenerate or duplicate billing.
    if persistent:
        assert _metered(db_url, org) == []
        with tenant_connection(TenantContext(*org, "owner")) as conn:
            user_day, org_month = spend_snapshot(conn, TenantContext(*org, "owner"))
        assert user_day == org_month == Decimal("0.25")
    else:
        assert actual_cost is not None and actual_cost > 0
        assert _metered(db_url, org) == [("research_query", actual_cost)]
        assert Decimal(trace["cost_usd"]) == actual_cost


def test_equivalent_organization_ids_share_the_budget_lock(org: tuple[str, str]) -> None:
    canonical = TenantContext(*org, "owner")
    alternate = TenantContext("{" + org[0].upper() + "}", org[1], "owner")
    with tenant_connection(alternate) as first:
        lock_query_budget(first, alternate)
        with tenant_connection(canonical) as second:
            # A second session must not acquire the same organization's key
            # just because the signed claim uses another valid UUID spelling.
            row = second.execute(
                "SELECT pg_try_advisory_xact_lock(191, hashtext(%s::uuid::text)) AS acquired",
                (canonical.org_id,),
            ).fetchone()
            assert row is not None and row["acquired"] is False
    with tenant_connection(canonical) as conn:
        row = conn.execute(
            "SELECT pg_try_advisory_xact_lock(191, hashtext(%s::uuid::text)) AS acquired",
            (canonical.org_id,),
        ).fetchone()
        assert row is not None and row["acquired"] is True
