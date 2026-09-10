"""Complete trace-or-error and resumable bounded persisted-event reads."""

import json
import uuid

import psycopg

from tests.conftest import requires_db
from tests.test_retrieval_api import _create, _headers
from tests.test_retrieval_api import (
    db_url as retrieval_db_url,
)
from tests.test_retrieval_api import (
    org as retrieval_org,
)
from tests.test_retrieval_api import (
    seeded as retrieval_seeded,
)

db_url = retrieval_db_url
org = retrieval_org
seeded = retrieval_seeded

pytestmark = requires_db


def test_event_history_page_and_replay_beyond_two_thousand(client, org, seeded, db_url):
    created = _create(client, org, seeded["workspace_id"])
    # Seed a separate running run; append-only guards prohibit extending a terminal run.
    run_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as c:
        c.execute(
            "INSERT INTO retrieval_runs (id,org_id,query_id,mode,status,config_hash,em"
            "bedding_provider,embedding_model,generation_provider,generation_model,pla"
            "nner_version) SELECT %s,org_id,query_id,'execute','queued',config_hash,em"
            "bedding_provider,embedding_model,generation_provider,generation_model,pla"
            "nner_version FROM retrieval_runs WHERE id=%s",
            (run_id, created["run_id"]),
        )
        c.execute(
            "INSERT INTO retrieval_events (run_id,org_id,seq,event_type,payload) "
            "SELECT %s,%s,n,CASE WHEN n=2201 THEN 'run_failed' ELSE 'run_started' "
            "END,'{}'::jsonb FROM generate_series(1,2201) n",
            (run_id, org[0]),
        )
    url = f"/v1/retrieval-runs/{run_id}"
    first = client.get(url + "/event-history", params={"limit": 200}, headers=_headers(*org))
    assert first.status_code == 200, first.text
    assert [e["seq"] for e in first.json()["items"]] == list(range(1, 201))
    following = client.get(
        url + "/event-history",
        params={"cursor": first.json()["next_cursor"]},
        headers=_headers(*org),
    )
    assert [e["seq"] for e in following.json()["items"]] == list(range(201, 401))
    replay = client.get(url + "/events", headers=_headers(*org))
    events = [
        json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")
    ]
    assert [e["seq"] for e in events] == list(range(1, 2202))
    assert events[-1]["type"] == "run_failed"
    resumed = client.get(url + "/events", headers={**_headers(*org), "Last-Event-ID": "200"})
    assert "id: 200\n" not in resumed.text
    assert "id: 201\n" in resumed.text
    assert "id: 2201\n" in resumed.text


def test_oversized_persisted_event_returns_typed_413_before_sse_headers(
    client, org, seeded, db_url
):
    created = _create(client, org, seeded["workspace_id"])
    run_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as c:
        c.execute(
            "INSERT INTO retrieval_runs (id,org_id,query_id,mode,status,config_hash,em"
            "bedding_provider,embedding_model,generation_provider,generation_model,pla"
            "nner_version) SELECT %s,org_id,query_id,'execute','queued',config_hash,em"
            "bedding_provider,embedding_model,generation_provider,generation_model,pla"
            "nner_version FROM retrieval_runs WHERE id=%s",
            (run_id, created["run_id"]),
        )
        c.execute(
            "INSERT INTO retrieval_events (run_id,org_id,seq,event_type,payload) "
            "VALUES (%s,%s,1,'run_started',%s)",
            (run_id, org[0], json.dumps({"large": "x" * (256 * 1024 + 1)})),
        )
    for suffix in ["", "/events", "/event-history"]:
        response = client.get(f"/v1/retrieval-runs/{run_id}" + suffix, headers=_headers(*org))
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "TRACE_TOO_LARGE"
