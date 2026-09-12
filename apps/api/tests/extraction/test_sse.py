"""Real HTTP streaming remains open for review and delivers later committed events."""

import json
import socket
import time
from threading import Thread

import httpx
import pytest
import uvicorn

from tests.extraction.test_review_atomicity import command


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
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def test_live_waiting_review_delivers_new_review_then_terminal(
    live_api, extraction_tenant, waiting_review_fixture
):
    fixture, tenant = waiting_review_fixture, extraction_tenant
    path = live_api + "/v1/extraction-runs/" + fixture["run"] + "/events"
    with httpx.stream("GET", path, headers=tenant["headers"], timeout=5) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        lines = stream.iter_lines()
        assert next(lines).startswith(":")
        response = httpx.post(
            live_api + "/v1/extractions/review",
            json=command(fixture["proposal"], "reject"),
            headers={**tenant["headers"], "Idempotency-Key": "live-review-key"},
        )
        assert response.status_code == 200, response.text
        events = [
            json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: ")
        ]
    assert events[-2]["type"] == "review_completed" and events[-1]["type"] == "run_succeeded"
    ids = [event["id"] for event in events]
    assert ids == sorted(set(ids))
    with httpx.stream(
        "GET", path, headers={**tenant["headers"], "Last-Event-ID": str(ids[-2])}, timeout=5
    ) as stream:
        resumed = [
            json.loads(line.removeprefix("data: "))
            for line in stream.iter_lines()
            if line.startswith("data: ")
        ]
    assert [event["id"] for event in resumed] == [ids[-1]]
