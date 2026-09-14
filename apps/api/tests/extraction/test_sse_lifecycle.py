"""Live SSE membership, disconnect, resume and oversized-frame proofs."""

import json
import queue
import socket
import time
import uuid
from threading import Event, Thread

import httpx
import psycopg
import pytest
import uvicorn
from psycopg.types.json import Jsonb

from app.auth import make_mock_token
from app.db import pool_for
from app.extraction import routes_events
from tests.extraction.test_access_boundaries import _foreign_owner
from tests.extraction.test_run_creation import _create

LIVE_TIMEOUT = httpx.Timeout(10.0, read=None)


class _RouteClock:
    """Keep the stdlib monotonic clock intact for asyncio, httpx and Uvicorn."""

    def __init__(self, real, clock):
        self._real = real
        self._clock = clock

    def monotonic(self):
        return self._clock["t"]

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def live_api(extraction_client):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(extraction_client.app, log_level="error"))
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "local extraction API never started"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def _wait_until(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.01)
    pytest.fail(message)


def _pump(stream, inbox):
    try:
        for line in stream.iter_lines():
            inbox.put(line)
        inbox.put(None)
    except Exception as exc:
        inbox.put(exc)


def _next_item(inbox, timeout, message):
    try:
        item = inbox.get(timeout=timeout)
    except queue.Empty:
        pytest.fail(message)
    return item


def _drain_authorized(inbox):
    preamble = _next_item(inbox, 5, "authorized stream never received SSE preamble")
    assert isinstance(preamble, str) and preamble.startswith(":")
    data = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            item = inbox.get(timeout=0.05)
        except queue.Empty:
            if data:
                return data
            continue
        if not isinstance(item, str):
            pytest.fail(f"authorized replay ended early: {item!r}")
        if item.startswith("data: "):
            data.append(json.loads(item.removeprefix("data: ")))
    assert data, "authorized stream received no replayed events"
    return data


def _collect_until_closed(inbox, timeout):
    lines = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            item = inbox.get(timeout=0.05)
        except queue.Empty:
            continue
        if item is None or isinstance(item, Exception):
            return lines, item
        lines.append(item)
    pytest.fail(f"stream did not terminate within {timeout}s; lines={lines!r}")


def _occupancy(url):
    with psycopg.connect(url, autocommit=True) as conn:
        idle = conn.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname=current_database() AND pid <> pg_backend_pid() "
            "AND state = 'idle in transaction'"
        ).fetchone()[0]
        active = conn.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname=current_database() AND pid <> pg_backend_pid() "
            "AND xact_start IS NOT NULL AND state <> 'idle'"
        ).fetchone()[0]
    stats = pool_for(url).get_stats()
    return {
        "idle_in_transaction": idle,
        "active_xact": active,
        "checked_out": stats["pool_size"] - stats["pool_available"],
    }


def _seed_event(url, tenant, payload=None):
    corpus = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO corpus_versions(id,label,status) VALUES (%s,'sse-foreign','superseded')",
            (corpus,),
        )
        conn.execute(
            "INSERT INTO extraction_runs(id,org_id,workspace_id,entity_id,modes,as_of,"
            "corpus_version_id,ontology_version,workflow_version,provider,model,policy_id,"
            "input_hash,idempotency_key,created_by,created_at) VALUES "
            "(%s,%s,%s,%s,ARRAY['kpi'],'2026-06-30Z',%s,'ontology/v1',"
            "'extraction-workflow/v3','mock','mock-structured-v1',%s,%s,%s,%s,'2026-01-01Z')",
            (
                run_id,
                tenant["org"],
                tenant["workspace"],
                tenant["entity"],
                corpus,
                tenant["policy"],
                "sha256:" + "a" * 64,
                run_id,
                tenant["user"],
            ),
        )
        event_id = conn.execute(
            "INSERT INTO extraction_run_events(org_id,run_id,event_type,payload) "
            "VALUES (%s,%s,'heartbeat',%s) RETURNING id",
            (tenant["org"], run_id, Jsonb(payload or {"count": 7})),
        ).fetchone()[0]
    return run_id, event_id


def _viewer(url, org):
    user = str(uuid.uuid4())
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'viewer')",
            (org, user),
        )
    return user, {"Authorization": f"Bearer {make_mock_token(org, user, 'viewer')}"}


def test_revoked_viewer_stream_drops_without_later_payload(
    live_api, extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    user, headers = _viewer(extraction_url, tenant["org"])
    path = live_api + "/v1/extraction-runs/" + fixture["run"] + "/events"
    inbox = queue.Queue()
    with httpx.stream("GET", path, headers=headers, timeout=LIVE_TIMEOUT) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        reader = Thread(target=_pump, args=(stream, inbox), daemon=True)
        reader.start()
        replayed = _drain_authorized(inbox)
        assert replayed
        with psycopg.connect(extraction_url) as conn:
            conn.execute(
                "DELETE FROM memberships WHERE org_id=%s AND user_id=%s",
                (tenant["org"], user),
            )
        _wait_until(
            lambda: extraction_client.get(
                "/v1/extraction-runs/" + fixture["run"] + "/events", headers=headers
            ).status_code
            == 403,
            5,
            "revoked membership still authorized a new events request",
        )
        time.sleep(0.3)
        with psycopg.connect(extraction_url) as conn:
            conn.execute(
                "INSERT INTO extraction_run_events(org_id,run_id,event_type,payload) "
                "VALUES (%s,%s,'heartbeat',%s)",
                (tenant["org"], fixture["run"], Jsonb({"count": 4242})),
            )
        later, _terminal = _collect_until_closed(inbox, 5)
        joined = "\n".join(later)
        assert "4242" not in joined
        for line in later:
            if line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
                assert payload.get("payload", {}).get("count") != 4242


def test_disconnect_releases_checkout_and_transaction(
    live_api, extraction_tenant, extraction_url, waiting_review_fixture, monkeypatch
):
    completed = Event()

    class ObservedResponse(routes_events.StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                completed.set()

    # Observe real server completion; a healthy poll releases its DB checkout
    # even while the response is still running, so an idle sample is insufficient.
    monkeypatch.setattr(routes_events, "StreamingResponse", ObservedResponse)
    tenant, fixture = extraction_tenant, waiting_review_fixture
    path = live_api + "/v1/extraction-runs/" + fixture["run"] + "/events"
    baseline = _occupancy(extraction_url)
    inbox = queue.Queue()
    with httpx.stream("GET", path, headers=tenant["headers"], timeout=LIVE_TIMEOUT) as stream:
        assert stream.status_code == 200
        reader = Thread(target=_pump, args=(stream, inbox), daemon=True)
        reader.start()
        replayed = _drain_authorized(inbox)
        assert replayed
        assert not completed.is_set(), "waiting-review stream ended before disconnect"
        # Shutdown wakes the reader blocked in recv as well as notifying the
        # server. Merely closing a socket in another thread need not wake recv.
        network = stream.extensions["network_stream"]
        network.get_extra_info("socket").shutdown(socket.SHUT_RDWR)
    reader.join(5)
    assert not reader.is_alive(), "client stream reader survived disconnect"
    assert completed.wait(5), "server streaming response survived disconnect"

    def resources_released():
        current = _occupancy(extraction_url)
        return all(current[key] <= baseline[key] for key in baseline)

    released = _wait_until(
        resources_released,
        5,
        "disconnect left a checked-out connection or active/idle transaction",
    )
    assert released
    assert _occupancy(extraction_url)["idle_in_transaction"] <= baseline["idle_in_transaction"]
    current = httpx.get(
        live_api + "/v1/extraction-runs/" + fixture["run"],
        headers=tenant["headers"],
        timeout=5,
    )
    assert current.status_code == 200, current.text


def test_heartbeat_uses_clock_seam_on_live_socket(
    live_api, extraction_tenant, waiting_review_fixture, monkeypatch
):
    clock = {"t": 0.0}
    monkeypatch.setattr(routes_events, "time", _RouteClock(time, clock))
    tenant, fixture = extraction_tenant, waiting_review_fixture
    path = live_api + "/v1/extraction-runs/" + fixture["run"] + "/events"
    inbox = queue.Queue()
    with httpx.stream("GET", path, headers=tenant["headers"], timeout=LIVE_TIMEOUT) as stream:
        assert stream.status_code == 200
        reader = Thread(target=_pump, args=(stream, inbox), daemon=True)
        reader.start()
        replayed = _drain_authorized(inbox)
        assert replayed
        leftover_deadline = time.monotonic() + 0.5
        while time.monotonic() < leftover_deadline:
            try:
                item = inbox.get(timeout=0.05)
            except queue.Empty:
                continue
            if isinstance(item, str) and item.startswith(": heartbeat"):
                pytest.fail("heartbeat emitted before the clock seam advanced")
            if not isinstance(item, str):
                pytest.fail(f"stream ended before heartbeat: {item!r}")
        clock["t"] = 21.0
        beat_deadline = time.monotonic() + 5
        while time.monotonic() < beat_deadline:
            try:
                item = inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if isinstance(item, str) and item.startswith(": heartbeat"):
                return
            if not isinstance(item, str):
                pytest.fail(f"stream ended before heartbeat: {item!r}")
        pytest.fail("heartbeat comment was not emitted after the clock seam advanced")


def test_foreign_and_other_run_resume_ids_are_404(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    other = _create(extraction_client, tenant, source_fixture)
    assert other.status_code == 202, other.text
    with psycopg.connect(extraction_url) as conn:
        other_event = conn.execute(
            "SELECT id FROM extraction_run_events WHERE run_id=%s ORDER BY id LIMIT 1",
            (other.json()["id"],),
        ).fetchone()[0]
    stranger = _foreign_owner(extraction_url)
    _, foreign_event = _seed_event(
        extraction_url, stranger, {"count": 9, "secret": "foreign-payload"}
    )
    path = f"/v1/extraction-runs/{fixture['run']}/events"
    for resume in (other_event, foreign_event):
        response = extraction_client.get(
            path, headers={**tenant["headers"], "Last-Event-ID": str(resume)}
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "NOT_FOUND"
        assert "foreign-payload" not in response.text


def test_initial_oversized_event_is_413_before_stream(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    pad = "oversized-secret-" + ("x" * 70000)
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO extraction_run_events(org_id,run_id,event_type,payload) "
            "VALUES (%s,%s,'heartbeat',%s)",
            (tenant["org"], fixture["run"], Jsonb({"count": 1, "secret": pad})),
        )
    response = extraction_client.get(
        f"/v1/extraction-runs/{fixture['run']}/events", headers=tenant["headers"]
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "EXTRACTION_TOO_LARGE"
    assert fixture["run"] in str(response.json()["error"]["details"])
    assert pad not in response.text
    assert "oversized-secret-" not in response.text
    assert not response.headers["content-type"].startswith("text/event-stream")
