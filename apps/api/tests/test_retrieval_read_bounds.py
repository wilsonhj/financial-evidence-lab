"""Complete trace-or-error and resumable bounded persisted-event reads."""

import json
import uuid

import psycopg
import pytest

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


def _running_run(conn, original):
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO retrieval_runs (id,org_id,query_id,mode,status,config_hash,"
        "embedding_provider,embedding_model,generation_provider,generation_model,planner_version)"
        " SELECT %s,org_id,query_id,'execute','queued',config_hash,embedding_provider,"
        "embedding_model,generation_provider,generation_model,planner_version"
        " FROM retrieval_runs WHERE id=%s",
        (run_id, original),
    )
    return run_id


@pytest.mark.parametrize("kind", ["events", "claims", "citations", "serialized_bytes"])
def test_full_trace_rejects_collection_or_byte_overflow(
    client, org, seeded, db_url, kind, monkeypatch
):
    from app import retrieval

    materialized = []
    original_rows = retrieval._trace_rows

    def traced_rows(*args):
        materialized.append(args[4])
        return original_rows(*args)

    monkeypatch.setattr(retrieval, "_trace_rows", traced_rows)
    created = _create(client, org, seeded["workspace_id"])
    with psycopg.connect(db_url) as c:
        run_id = _running_run(c, created["run_id"])
        if kind in {"events", "serialized_bytes"}:
            c.execute(
                "INSERT INTO retrieval_events (run_id, org_id, seq, event_type, payload)"
                " SELECT %s, %s, n, 'run_started', jsonb_build_object('text', "
                "repeat('x', %s)) FROM generate_series(1, %s) n",
                (
                    run_id,
                    org[0],
                    200000 if kind == "serialized_bytes" else 0,
                    100 if kind == "serialized_bytes" else 10001,
                ),
            )
        else:
            c.execute(
                "INSERT INTO claims (id, org_id, run_id, ord, text, status) SELECT "
                "gen_random_uuid(), %s, %s, n, 'Claim', 'unsupported' FROM "
                "generate_series(0, %s) n",
                (org[0], run_id, 1000 if kind == "claims" else 0),
            )
            if kind == "citations":
                c.execute(
                    "INSERT INTO retrieval_candidates (id, org_id, run_id, "
                    "retrieval_item_id, lane, variant_index, lane_rank, raw_score, "
                    "rrf_contribution, fused_score, accepted, timing_ms) SELECT "
                    "gen_random_uuid(), org_id, %s, retrieval_item_id, lane, "
                    "variant_index, lane_rank, raw_score, rrf_contribution, fused_score,"
                    " true, timing_ms FROM retrieval_candidates WHERE run_id=%s AND "
                    "accepted LIMIT 1",
                    (run_id, created["run_id"]),
                )
                c.execute(
                    "INSERT INTO citations (id, org_id, run_id, claim_id, "
                    "retrieval_item_id, source_span_id, status) SELECT "
                    "gen_random_uuid(), cl.org_id, cl.run_id, cl.id, "
                    "rc.retrieval_item_id, ri.source_span_id, 'entailed' FROM claims cl "
                    "JOIN retrieval_candidates rc ON rc.run_id=cl.run_id JOIN "
                    "retrieval_items ri ON ri.id=rc.retrieval_item_id CROSS JOIN "
                    "generate_series(1, 16000) WHERE cl.run_id=%s",
                    (run_id,),
                )
                retrieval._check_citation_count(c, run_id)
                c.execute(
                    "INSERT INTO citations (id, org_id, run_id, claim_id, retrieval_item_id,"
                    " source_span_id, status) SELECT gen_random_uuid(), org_id, run_id,"
                    " claim_id, retrieval_item_id, source_span_id, status FROM citations"
                    " WHERE run_id=%s LIMIT 1",
                    (run_id,),
                )
    response = client.get(f"/v1/retrieval-runs/{run_id}", headers=_headers(*org))
    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit_kind"] == kind
    if kind == "citations":
        assert "citations" not in materialized


def test_sse_closes_connections_before_yield_and_stops_at_cancellation(
    client, org, seeded, db_url, monkeypatch
):
    from contextlib import contextmanager

    from app import retrieval
    from app.auth import TenantContext

    created = _create(client, org, seeded["workspace_id"])
    with psycopg.connect(db_url) as c:
        run_id = _running_run(c, created["run_id"])
        c.execute(
            "INSERT INTO retrieval_events (run_id, org_id, seq, event_type, payload) "
            "SELECT %s, %s, n, 'run_started', '{}' FROM generate_series(1, 401) n",
            (run_id, org[0]),
        )
    real_connection = retrieval.tenant_connection
    real_rows = retrieval._event_rows
    active = []
    sizes = []

    @contextmanager
    def connection(*args, **kwargs):
        with real_connection(*args, **kwargs) as conn:
            active.append(True)
            try:
                yield conn
            finally:
                active.pop()

    def rows(*args, **kwargs):
        result = real_rows(*args, **kwargs)
        sizes.append(len(result))
        return result

    monkeypatch.setattr(retrieval, "tenant_connection", connection)
    monkeypatch.setattr(retrieval, "_event_rows", rows)
    stream = retrieval._sse_stream(TenantContext(org[0], org[1], "owner"), run_id, 0)
    assert next(stream).startswith(":")
    assert not active
    assert next(stream).startswith("id: 1\n")
    assert not active
    stream.close()
    assert sizes == [200]
    assert not active
    sizes.clear()
    frames = list(retrieval._sse_stream(TenantContext(org[0], org[1], "owner"), run_id, 199))
    assert sizes == [200, 2]
    assert frames[1].startswith("id: 200\n")
    assert frames[-1].startswith("id: 401\n")
    assert not active


def test_later_oversized_sse_batch_aborts_without_synthetic_terminal(client, org, seeded, db_url):
    from fastapi import HTTPException

    from app import retrieval
    from app.auth import TenantContext

    created = _create(client, org, seeded["workspace_id"])
    with psycopg.connect(db_url) as c:
        run_id = _running_run(c, created["run_id"])
        c.execute(
            "INSERT INTO retrieval_events (run_id, org_id, seq, event_type, payload) "
            "SELECT %s, %s, n, 'run_started', jsonb_build_object('text', repeat('x', "
            "CASE WHEN n=201 THEN 262145 ELSE 0 END)) FROM generate_series(1, 201) n",
            (run_id, org[0]),
        )
    stream = retrieval._sse_stream(TenantContext(org[0], org[1], "owner"), run_id, 0)
    emitted = [next(stream) for _ in range(201)]
    assert emitted[-1].startswith("id: 200\n")
    with pytest.raises(HTTPException) as err:
        next(stream)
    assert err.value.status_code == 413
    assert not any("run_failed" in frame or "run_completed" in frame for frame in emitted)
    response = client.get(
        f"/v1/retrieval-runs/{run_id}/event-history",
        params={"order": "desc"},
        headers=_headers(*org),
    )
    assert response.status_code == 413


def test_query_history_traverses_more_than_two_hundred_runs(client, org, seeded, db_url):
    created = _create(client, org, seeded["workspace_id"])
    with psycopg.connect(db_url) as c:
        for _ in range(250):
            _running_run(c, created["run_id"])
        expected = [
            str(r[0])
            for r in c.execute(
                "SELECT id FROM retrieval_runs WHERE query_id=%s ORDER BY started_at,id",
                (created["query_id"],),
            )
        ]
    url = f"/v1/queries/{created['query_id']}"
    assert client.get(url, headers=_headers(*org)).status_code == 409
    for order, wanted in [("asc", expected), ("desc", expected[::-1])]:
        seen = []
        cursor = None
        while True:
            params = {"limit": 50, "order": order}
            if cursor:
                params["cursor"] = cursor
            response = client.get(url, params=params, headers=_headers(*org))
            assert response.status_code == 200
            seen.extend(r["run_id"] for r in response.json()["runs"])
            cursor = response.headers.get("X-FEL-Next-Cursor")
            if not cursor:
                break
        assert seen == wanted


def test_trace_plan_bytes_are_checked_before_payload_transfer(
    client, org, seeded, db_url, monkeypatch
):
    from app import retrieval

    created = _create(client, org, seeded["workspace_id"])
    query_id = str(uuid.uuid4())
    with psycopg.connect(db_url) as c:
        c.execute(
            "INSERT INTO queries (id, org_id, workspace_id, question, effective_as_of, "
            "plan, corpus_version_id, index_version_id, planner_version, created_by) "
            "SELECT %s, org_id, workspace_id, question, effective_as_of, "
            "plan||jsonb_build_object('large', repeat('x', 17*1024*1024)), "
            "corpus_version_id, index_version_id, planner_version, created_by FROM "
            "queries WHERE id=%s",
            (query_id, created["query_id"]),
        )
        run_id = _running_run(c, created["run_id"])
        # query_id is immutable, so a fresh run must point at the large query.
        new_run = str(uuid.uuid4())
        c.execute(
            "INSERT INTO retrieval_runs (id, org_id, query_id, mode, status, "
            "config_hash, embedding_provider, embedding_model, generation_provider, "
            "generation_model, planner_version) SELECT %s, org_id, %s, mode, status, "
            "config_hash, embedding_provider, embedding_model, generation_provider, "
            "generation_model, planner_version FROM retrieval_runs WHERE id=%s",
            (new_run, query_id, run_id),
        )
    from contextlib import contextmanager

    original_connection = retrieval.tenant_connection
    transferred = []

    class CursorProbe:
        def __init__(self, cursor):
            self.cursor = cursor

        def check(self, row):
            if row and "plan" in row and len(json.dumps(row["plan"]).encode()) > 16 * 1024 * 1024:
                transferred.append(True)
            return row

        def fetchone(self):
            return self.check(self.cursor.fetchone())

        def fetchall(self):
            return [self.check(row) for row in self.cursor.fetchall()]

    class ConnectionProbe:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, *args, **kwargs):
            return CursorProbe(self.conn.execute(*args, **kwargs))

    @contextmanager
    def connection(*args, **kwargs):
        with original_connection(*args, **kwargs) as conn:
            yield ConnectionProbe(conn)

    monkeypatch.setattr(retrieval, "tenant_connection", connection)
    called = []
    original = retrieval._group_candidates

    def tracked(rows):
        called.append(True)
        return original(rows)

    monkeypatch.setattr(retrieval, "_group_candidates", tracked)
    response = client.get(f"/v1/retrieval-runs/{new_run}", headers=_headers(*org))
    assert response.status_code == 413
    assert not called

    assert not transferred


def test_contribution_ceiling_is_checked_before_distinct_aggregation(client, org, seeded, db_url):
    """32,000 valid lane contributions pass the row probe; row 32,001 fails first."""
    from psycopg.rows import dict_row

    from app import retrieval

    created = _create(client, org, seeded["workspace_id"])
    index_id, query_id, run_id = [str(uuid.uuid4()) for _ in range(3)]
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        conn.execute(
            "INSERT INTO retrieval_index_versions (id, corpus_version_id, "
            "chunker_version, chunker_config, config_hash, embedding_provider, "
            "embedding_model) SELECT %s, corpus_version_id, chunker_version, "
            "chunker_config, 'sha256:'||%s, embedding_provider, embedding_model FROM "
            "retrieval_index_versions WHERE id=%s",
            (index_id, uuid.uuid4().hex * 2, seeded["index_version_id"]),
        )
        conn.execute(
            "UPDATE retrieval_index_versions SET status='building' WHERE id=%s", (index_id,)
        )
        template = conn.execute(
            "SELECT * FROM retrieval_items WHERE index_version_id=%s AND kind='passage' LIMIT 1",
            (seeded["index_version_id"],),
        ).fetchone()
        spans = conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) SELECT gen_random_uuid(), document_version_id, "
            "section_id, start_char, end_char, text_hash FROM source_spans CROSS JOIN "
            "generate_series(1, 2001) WHERE id=%s RETURNING id",
            (template["source_span_id"],),
        ).fetchall()
        conn.execute(
            "INSERT INTO retrieval_items (id, index_version_id, kind, entity_id, "
            "document_id, document_version_id, section_id, source_span_id, content, "
            "content_sha256, start_char, end_char, token_count) SELECT "
            "gen_random_uuid(), %s, 'passage', ri.entity_id, ri.document_id, "
            "ri.document_version_id, ri.section_id, ss.id, ri.content, "
            "ri.content_sha256, ri.start_char, ri.end_char, ri.token_count FROM "
            "retrieval_items ri CROSS JOIN source_spans ss WHERE ri.id=%s AND "
            "ss.id=ANY(%s)",
            (index_id, template["id"], [row["id"] for row in spans]),
        )
        conn.execute(
            "UPDATE retrieval_index_versions SET status='ready',published_at=now() WHERE id=%s",
            (index_id,),
        )
        conn.execute(
            "INSERT INTO queries (id, org_id, workspace_id, question, effective_as_of, "
            "plan, corpus_version_id, index_version_id, planner_version, created_by) "
            "SELECT %s, org_id, workspace_id, question, effective_as_of, plan, "
            "corpus_version_id, %s, planner_version, created_by FROM queries WHERE id=%s",
            (query_id, index_id, created["query_id"]),
        )
        conn.execute(
            "INSERT INTO retrieval_runs (id, org_id, query_id, mode, status, "
            "config_hash, embedding_provider, embedding_model, generation_provider, "
            "generation_model, planner_version) SELECT %s, org_id, %s, mode, 'queued', "
            "config_hash, embedding_provider, embedding_model, generation_provider, "
            "generation_model, planner_version FROM retrieval_runs WHERE id=%s",
            (run_id, query_id, created["run_id"]),
        )
        conn.execute(
            "INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, "
            "lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, "
            "accepted, timing_ms) SELECT gen_random_uuid(), %s, %s, ri.id, lane.name, "
            "v.n, 1, '1', '0', '0', false, 0 FROM (SELECT id FROM retrieval_items WHERE "
            "index_version_id=%s ORDER BY id LIMIT 2000) ri CROSS JOIN (VALUES "
            "('dense'), ('lexical'), ('facts'), ('tables')) lane(name) CROSS JOIN "
            "generate_series(0, 3) v(n)",
            (org[0], run_id, index_id),
        )
        retrieval._check_candidate_counts(conn, run_id)
        conn.execute(
            "INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, "
            "lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, "
            "accepted, timing_ms) SELECT gen_random_uuid(), %s, %s, id, 'dense', 0, 1, "
            "'1', '0', '0', false, 0 FROM retrieval_items WHERE index_version_id=%s "
            "ORDER BY id DESC LIMIT 1",
            (org[0], run_id, index_id),
        )
    response = client.get(f"/v1/retrieval-runs/{run_id}", headers=_headers(*org))
    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit_kind"] == "candidate_contributions"
