"""M2-015 retrieval API integration tests (create/read/trace/SSE/rerun/feedback).

These exercise the full persisted-trace path against a real pgvector Postgres
with db/migrations applied: an active published index is built over a small
corpus, a query is created (which executes the pipeline synchronously and
persists the whole run), and the trace/SSE/rerun/feedback surfaces are asserted
against the frozen contract. They skip cleanly when TEST_DATABASE_URL is unset.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from tests.conftest import TEST_DATABASE_URL, ensure_retrieval_database, requires_db

pytestmark = requires_db

import app.retrieval as retrieval  # noqa: E402
from fel_providers import MockEmbeddingProvider  # noqa: E402
from fel_retrieval import build_and_publish, make_index_version_spec  # noqa: E402


@pytest.fixture()
def db_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the retrieval suite (and the app) at the isolated retrieval DB.

    Overrides the shared conftest ``db_url`` for this module only: these tests
    commit into delete-immutable tables, so they must not touch the base DB the
    workers/ingestion suites clean between runs.
    """
    assert TEST_DATABASE_URL is not None
    url = ensure_retrieval_database(TEST_DATABASE_URL)
    monkeypatch.setenv("FEL_DATABASE_URL", url)
    return url


_PROVIDER = "mock"
_MODEL = "mock-embed-v1"
_AS_OF = datetime(2026, 1, 1, tzinfo=UTC)
_PUBLISHED = datetime(2025, 6, 1, tzinfo=UTC)

_SENTENCES = [
    "Revenue was $100 million in fiscal 2025.",
    "Cost of sales was $40 million in fiscal 2025.",
    "Operating income reached $35 million for the year.",
    "Net income was $28 million, up from the prior year.",
    "Cash and equivalents totaled $52 million at year end.",
    "Total assets stood at $410 million as of December 31.",
]


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _headers(org_id: str, user_id: str, role: str = "owner") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_mock_token(org_id, user_id, role)}"}


def _seed_indexed_workspace(
    conn: Any, org_id: str, *, embedding_provider: str = _PROVIDER
) -> dict[str, str]:
    """Seed one entity's corpus, publish an active index, create a workspace.

    ``embedding_provider`` pins the published index's provider column; it defaults
    to the mock. A non-mock pin still builds with the mock embedder (512-dim
    vectors) so the run's pin resolves to an unavailable provider at query time.
    """
    entity_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    document_version_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    fact_id = str(uuid.uuid4())
    corpus_version_id = str(uuid.uuid4())
    heading_path = ["ITEM 8", "FINANCIAL STATEMENTS"]

    canonical = "\n".join(_SENTENCES)
    spans: list[dict[str, Any]] = []
    offset = 0
    for sentence in _SENTENCES:
        start, end = offset, offset + len(sentence)
        spans.append(
            {
                "id": str(uuid.uuid4()),
                "section_id": section_id,
                "start_char": start,
                "end_char": end,
                "text": sentence,
                "text_hash": _sha(sentence),
                "heading_path": heading_path,
            }
        )
        offset = end + 1

    conn.execute(
        "INSERT INTO documents (id, entity_id, accession, source_url, content_hash, "
        "storage_key, published_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            document_id,
            entity_id,
            f"acc-{uuid.uuid4()}",
            "https://example.test/doc",
            _sha(canonical),
            f"raw/{document_id}",
            _PUBLISHED,
        ),
    )
    conn.execute(
        "INSERT INTO document_versions (id, document_id, parser_version, "
        "normalizer_version, canonical_text_key) VALUES (%s, %s, %s, %s, %s)",
        (document_version_id, document_id, "p/1", "n/1", f"text/sha256/{document_id}"),
    )
    conn.execute(
        "INSERT INTO sections (id, document_version_id, heading, heading_path, ord, "
        "start_char, end_char) VALUES (%s, %s, %s, %s, 0, 0, %s)",
        (section_id, document_version_id, "FINANCIAL STATEMENTS", heading_path, len(canonical)),
    )
    for span in spans:
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                span["id"],
                document_version_id,
                section_id,
                span["start_char"],
                span["end_char"],
                span["text_hash"],
            ),
        )
    conn.execute(
        "INSERT INTO financial_facts (id, entity_id, document_version_id, concept, value, "
        "unit, period_type, source_span_id, fact_key) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'duration', %s, %s)",
        (
            fact_id,
            entity_id,
            document_version_id,
            "Revenues",
            "100000000",
            "USD",
            spans[0]["id"],
            "revenues:FY2025:USD",
        ),
    )
    conn.execute(
        "INSERT INTO tables_meta (id, document_version_id, section_id, ord, headers, rows) "
        "VALUES (%s, %s, %s, 0, %s::jsonb, %s::jsonb)",
        (
            table_id,
            document_version_id,
            section_id,
            json.dumps(["metric", "value"]),
            json.dumps([{"source_span_id": spans[1]["id"]}, {"source_span_id": None}]),
        ),
    )
    conn.execute(
        "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'draft')",
        (corpus_version_id, f"corpus-{corpus_version_id[:8]}"),
    )
    conn.execute(
        "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id) "
        "VALUES (%s, %s)",
        (corpus_version_id, document_version_id),
    )

    corpus = {
        "entity_id": entity_id,
        "document_id": document_id,
        "document_version_id": document_version_id,
        "form": "10-K",
        "canonical_text": canonical,
        "source_spans": spans,
        "financial_facts": [{"id": fact_id, "source_span_id": spans[0]["id"], "period": "FY2025"}],
        "tables": [
            {
                "id": table_id,
                "section_id": section_id,
                "heading_path": heading_path,
                "rows": [{"source_span_id": spans[1]["id"]}, {"source_span_id": None}],
            }
        ],
    }
    spec = make_index_version_spec(
        corpus_version_id=corpus_version_id,
        embedding_provider=embedding_provider,
        embedding_model=_MODEL,
    )
    build_and_publish(
        conn, spec=spec, corpus=corpus, provider=MockEmbeddingProvider(512), activate=True
    )

    workspace_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, "
        "fiscal_calendar, as_of) VALUES (%s, %s, %s, %s, 'USD', 'DEC', %s)",
        (workspace_id, org_id, "ws", entity_id, _AS_OF),
    )
    return {
        "workspace_id": workspace_id,
        "entity_id": entity_id,
        "index_version_id": spec.id,
        "corpus_version_id": corpus_version_id,
    }


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


def _create(client: TestClient, org: tuple[str, str], ws: str, **body: Any) -> dict[str, Any]:
    payload = {"question": "What was revenue in fiscal 2025?", **body}
    resp = client.post(
        f"/v1/workspaces/{ws}/queries",
        json=payload,
        headers={**_headers(*org), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 202, resp.text
    created: dict[str, Any] = resp.json()
    return created


def test_create_read_trace_happy_path(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    assert created["events_url"] == f"/v1/retrieval-runs/{created['run_id']}/events"

    snap = client.get(f"/v1/queries/{created['query_id']}", headers=_headers(*org))
    assert snap.status_code == 200, snap.text
    body = snap.json()
    assert body["question"] == "What was revenue in fiscal 2025?"
    assert body["plan"]["schema_version"] == "query-plan/v1"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["run_id"] == created["run_id"]
    assert body["runs"][0]["status"] == "succeeded"
    assert body["runs"][0]["mode"] == "execute"

    trace = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org))
    assert trace.status_code == 200, trace.text
    tj = trace.json()
    assert tj["status"] == "succeeded"
    assert tj["lineage"]["index_version_id"] == seeded["index_version_id"]
    assert tj["lineage"]["planner_version"] == "synonym-planner/v1"
    assert tj["events"][0]["type"] == "run_started"
    assert tj["events"][-1]["type"] == "run_completed"
    assert tj["candidates"], "expected fused candidates"
    assert all(c["contributions"] for c in tj["candidates"])
    assert tj["decisions"], "expected fusion/context decisions"
    assert set(tj["budget_usage"]) == {
        "context_items",
        "context_tokens",
        "input_tokens",
        "output_tokens",
    }


def test_claims_generated_and_persisted(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    """M2-020: the run decomposes selected context into atomic claims that are
    persisted with their citation edges and surfaced in the trace."""
    created = _create(client, org, seeded["workspace_id"])
    trace = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org)).json()

    claims = trace["claims"]
    assert claims, "expected generated claims"
    # One atomic claim per accepted context item, all in the closed status set.
    accepted_items = {c["item_id"] for c in trace["candidates"] if c["accepted"]}
    cited_items = {cit["item_id"] for cl in claims for cit in cl["citations"]}
    assert cited_items, "expected citation edges"
    assert cited_items <= accepted_items, "citations must target accepted candidates"
    for claim in claims:
        assert claim["status"] in {
            "supported",
            "partially_supported",
            "contradicted",
            "derived",
            "unsupported",
        }
        for citation in claim["citations"]:
            assert citation["status"] in {"entailed", "partial", "contradictory", "irrelevant"}
            assert isinstance(citation["numeric_checks"], dict)

    # claim_generated events are traced; budget records generation usage.
    assert any(e["type"] == "claim_generated" for e in trace["events"])
    assert trace["budget_usage"]["output_tokens"] >= 1


def test_trace_replay_byte_stable(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    first = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org))
    second = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org))
    assert first.content == second.content
    assert first.headers["content-type"].startswith("application/json")


def _parse_sse(text: str) -> tuple[list[int], list[dict[str, Any]], bool]:
    ids: list[int] = []
    events: list[dict[str, Any]] = []
    has_heartbeat = False
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if block.startswith(":"):
            has_heartbeat = True
            continue
        for line in block.split("\n"):
            if line.startswith("id: "):
                ids.append(int(line[4:]))
            elif line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return ids, events, has_heartbeat


def test_sse_full_stream(client: TestClient, org: tuple[str, str], seeded: dict[str, str]) -> None:
    created = _create(client, org, seeded["workspace_id"])
    resp = client.get(f"/v1/retrieval-runs/{created['run_id']}/events", headers=_headers(*org))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    ids, events, has_heartbeat = _parse_sse(resp.text)
    assert has_heartbeat, "expected a heartbeat comment"
    assert ids == sorted(ids) and ids[0] == 1
    assert ids == list(range(1, len(ids) + 1))
    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "run_completed"
    assert all(e["schema_version"] == "retrieval-event/v1" for e in events)


def test_sse_reconnect_last_event_id(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    full = client.get(f"/v1/retrieval-runs/{created['run_id']}/events", headers=_headers(*org))
    ids, _events, _ = _parse_sse(full.text)
    mid = ids[len(ids) // 2]

    resumed = client.get(
        f"/v1/retrieval-runs/{created['run_id']}/events",
        headers={**_headers(*org), "Last-Event-ID": str(mid)},
    )
    r_ids, _r_events, _ = _parse_sse(resumed.text)
    assert r_ids, "reconnect returned no later events"
    assert min(r_ids) == mid + 1
    assert r_ids == sorted(r_ids)
    assert set(r_ids).isdisjoint({i for i in ids if i <= mid})


def test_rerun_parent_linked_and_parent_frozen(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    parent_trace_before = client.get(
        f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org)
    ).content

    rerun = client.post(
        f"/v1/queries/{created['query_id']}/reruns",
        headers={**_headers(*org), "Idempotency-Key": "idempotency-test-rerun-key"},
    )
    assert rerun.status_code == 202, rerun.text
    child_run_id = rerun.json()["run_id"]
    assert child_run_id != created["run_id"]

    child = client.get(f"/v1/retrieval-runs/{child_run_id}", headers=_headers(*org)).json()
    assert child["parent_run_id"] == created["run_id"]
    assert child["status"] == "succeeded"

    snap = client.get(f"/v1/queries/{created['query_id']}", headers=_headers(*org)).json()
    assert len(snap["runs"]) == 2

    parent_trace_after = client.get(
        f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org)
    ).content
    assert parent_trace_before == parent_trace_after


def test_feedback_append(client: TestClient, org: tuple[str, str], seeded: dict[str, str]) -> None:
    created = _create(client, org, seeded["workspace_id"])
    trace = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org)).json()
    item_id = trace["candidates"][0]["item_id"]

    resp = client.post(
        f"/v1/retrieval-runs/{created['run_id']}/feedback",
        json={"item_id": item_id, "label": "relevant", "reason": "on point"},
        headers={**_headers(*org), "Idempotency-Key": "idempotency-test-feedback-key"},
    )
    assert resp.status_code == 201, resp.text


def test_planner_validation_returns_422(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    resp = client.post(
        f"/v1/workspaces/{seeded['workspace_id']}/queries",
        json={"question": "revenue?", "periods": ["not-a-period"]},
        headers={**_headers(*org), "Idempotency-Key": "idempotency-test-badplan-key"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "INVALID_PERIOD"


def test_idempotent_create_returns_same_run(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    key = "idempotency-test-idem-key"
    headers = {**_headers(*org), "Idempotency-Key": key}
    payload = {"question": "What was revenue in fiscal 2025?"}
    first = client.post(
        f"/v1/workspaces/{seeded['workspace_id']}/queries", json=payload, headers=headers
    )
    second = client.post(
        f"/v1/workspaces/{seeded['workspace_id']}/queries", json=payload, headers=headers
    )
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    with psycopg.connect(db_url, autocommit=True) as conn:
        count = conn.execute(
            "SELECT count(*) FROM retrieval_runs WHERE query_id = %s",
            (first.json()["query_id"],),
        ).fetchone()
        assert count is not None and count[0] == 1


def _run_row(db_url: str, run_id: str) -> dict[str, Any]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        run = conn.execute(
            "SELECT status, error FROM retrieval_runs WHERE id = %s", (run_id,)
        ).fetchone()
        assert run is not None
        last_event = conn.execute(
            "SELECT event_type FROM retrieval_events WHERE run_id = %s ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        candidate_count = conn.execute(
            "SELECT count(*) FROM retrieval_candidates WHERE run_id = %s", (run_id,)
        ).fetchone()
    return {
        "status": run[0],
        "error": run[1],
        "last_event": last_event[0] if last_event else None,
        "candidate_count": candidate_count[0] if candidate_count else 0,
    }


def test_unknown_pinned_provider_persists_failed_run(
    client: TestClient, org: tuple[str, str], db_url: str
) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        seeded = _seed_indexed_workspace(conn, org[0], embedding_provider="openai")

    created = _create(client, org, seeded["workspace_id"])

    row = _run_row(db_url, created["run_id"])
    assert row["status"] == "failed"
    assert row["last_event"] == "run_failed"
    assert row["error"]["code"] == "EMBEDDING_PROVIDER_UNAVAILABLE"
    assert row["candidate_count"] == 0

    trace = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org))
    assert trace.status_code == 200, trace.text
    assert trace.json()["status"] == "failed"


def test_lane_failure_persists_failed_run(
    client: TestClient,
    org: tuple[str, str],
    seeded: dict[str, str],
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_conn: Any, _query: Any) -> list[Any]:
        raise RuntimeError("lane exploded")

    monkeypatch.setitem(retrieval._LANE_FUNCS, "dense", _boom)

    created = _create(client, org, seeded["workspace_id"])

    row = _run_row(db_url, created["run_id"])
    assert row["status"] == "failed"
    assert row["last_event"] == "run_failed"
    assert row["error"]["code"] == "LANE_EXECUTION_FAILED"
    assert row["candidate_count"] == 0


def test_feedback_non_candidate_item_is_422(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    created = _create(client, org, seeded["workspace_id"])

    bad = client.post(
        f"/v1/retrieval-runs/{created['run_id']}/feedback",
        json={"item_id": str(uuid.uuid4()), "label": "relevant"},
        headers={**_headers(*org), "Idempotency-Key": "idempotency-test-feedback-bad-key"},
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["error"]["code"] == "INVALID_FEEDBACK_ITEM"

    trace = client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=_headers(*org)).json()
    item_id = trace["candidates"][0]["item_id"]
    good = client.post(
        f"/v1/retrieval-runs/{created['run_id']}/feedback",
        json={"item_id": item_id, "label": "relevant"},
        headers={**_headers(*org), "Idempotency-Key": "idempotency-test-feedback-good-key"},
    )
    assert good.status_code == 201, good.text


def test_create_query_p95_smoke(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    """Smoke-level p95 gate over the seeded corpus (mock providers).

    Not a benchmark: a generous budget that will not flake on CI runners, sized
    ~4x locally observed latency. Guards against gross regressions only.
    """
    n = 20
    durations: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        resp = client.post(
            f"/v1/workspaces/{seeded['workspace_id']}/queries",
            json={"question": "What was revenue in fiscal 2025?"},
            headers={**_headers(*org), "Idempotency-Key": str(uuid.uuid4())},
        )
        durations.append(time.perf_counter() - start)
        assert resp.status_code == 202, resp.text

    durations.sort()
    p95 = durations[-2]  # nearest-rank p95 of 20 samples (ceil(0.95*20) = 19th)
    assert p95 < 2.0, f"p95 create-query latency {p95:.3f}s exceeded smoke budget"


def test_rls_cross_org_is_404(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    created = _create(client, org, seeded["workspace_id"])

    other_org, other_user = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO organizations (id, name) VALUES (%s, %s)", (other_org, other_org[:8])
        )
        conn.execute(
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (other_org, other_user),
        )
    other = _headers(other_org, other_user)

    assert client.get(f"/v1/queries/{created['query_id']}", headers=other).status_code == 404
    assert client.get(f"/v1/retrieval-runs/{created['run_id']}", headers=other).status_code == 404
    assert (
        client.get(f"/v1/retrieval-runs/{created['run_id']}/events", headers=other).status_code
        == 404
    )
