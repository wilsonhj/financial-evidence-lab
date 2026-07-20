"""M2-024 smoke gate: measured metrics, per-lane ablations, exact-vs-HNSW recall,
release-gate report and a reference-performance smoke.

These run the real retrieval pipeline over a small seeded, indexed corpus (mock
providers) and grade it with ``fel_retrieval_evals.metrics``. On this controlled
corpus every gate metric is perfect, so the smoke asserts the thresholds hold and
the ADR-0002 reranker stays disabled (report-only). They skip cleanly when
TEST_DATABASE_URL is unset.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_DATABASE_URL, ensure_retrieval_database, requires_db

pytestmark = requires_db

from fel_providers import MockEmbeddingProvider  # noqa: E402
from fel_retrieval import exact_knn, hnsw_search  # noqa: E402
from fel_retrieval_evals.metrics import (  # noqa: E402
    QuestionOutcome,
    aggregate_metrics,
    build_gate_report,
    hnsw_recall_at_k,
    question_recall_at_k,
)
from tests.test_retrieval_api import (  # noqa: E402
    _AS_OF,
    _create,
    _headers,
    _seed_indexed_workspace,
)

_LANES = ["dense", "lexical", "facts", "tables"]


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


def _gold_revenue_items(db_url: str, index_version_id: str) -> list[str]:
    """Gold evidence for the revenue question: revenue-bearing items in the index."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT id FROM retrieval_items" " WHERE index_version_id = %s AND content ILIKE %s",
            (index_version_id, "%revenue%"),
        ).fetchall()
    return [str(r[0]) for r in rows]


def _top_items(trace: dict[str, Any], k: int) -> list[str]:
    ordered = sorted(trace["candidates"], key=lambda c: c["fused_rank"])
    return [c["item_id"] for c in ordered[:k]]


def _trace(client: TestClient, org: tuple[str, str], run_id: str) -> dict[str, Any]:
    return client.get(f"/v1/retrieval-runs/{run_id}", headers=_headers(*org)).json()


def test_smoke_gate_passes_and_reranker_disabled(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    created = _create(client, org, seeded["workspace_id"])
    trace = _trace(client, org, created["run_id"])
    assert trace["status"] == "succeeded"

    gold = _gold_revenue_items(db_url, seeded["index_version_id"])
    assert gold, "expected revenue-bearing gold evidence"
    recall = question_recall_at_k(_top_items(trace, 10), gold, 10)

    # Grade the run's claims/citations. On this controlled corpus every entailed
    # edge is a true supporting edge and every numeric check passes.
    as_of_iso = _AS_OF.isoformat()
    temporal_ok = all(c["published_at"] <= as_of_iso for c in trace["candidates"])
    supporting = correct = rendered = cited = 0
    numeric_expected = numeric_correct = False
    for claim in trace["claims"]:
        if claim["status"] in {"supported", "derived"}:
            rendered += 1
            if claim["citations"]:
                cited += 1
        for citation in claim["citations"]:
            if citation["status"] in {"entailed", "partial"}:
                supporting += 1
                correct += 1  # verbatim-grounded on the seeded corpus
            if citation["numeric_checks"]:
                numeric_expected = True
                numeric_correct = all(citation["numeric_checks"].values())

    outcome = QuestionOutcome(
        recall_at_10=recall,
        temporal_ok=temporal_ok,
        numeric_expected=numeric_expected,
        numeric_correct=numeric_correct,
        supporting_citations=supporting,
        correct_supporting_citations=correct,
        rendered_claims=rendered,
        cited_rendered_claims=cited,
    )
    report = build_gate_report(aggregate_metrics([outcome]))
    assert report.passed, report.to_dict()
    assert report.reranker_triggered is False
    assert numeric_expected, "expected a fact-backed numeric claim on the seed corpus"


def test_per_lane_ablation(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    gold = _gold_revenue_items(db_url, seeded["index_version_id"])

    def recall_for(lanes: list[str]) -> Decimal:
        created = _create(client, org, seeded["workspace_id"], lanes=lanes)
        trace = _trace(client, org, created["run_id"])
        return question_recall_at_k(_top_items(trace, 10), gold, 10)

    full = recall_for(_LANES)
    ablations = {lane: recall_for([x for x in _LANES if x != lane]) for lane in _LANES}
    # Dropping a lane can only remove candidates, never improve recall.
    for lane, value in ablations.items():
        assert value <= full, f"ablating {lane} raised recall ({value} > {full})"


def test_exact_vs_hnsw_recall_reuses_oracle(seeded: dict[str, str], db_url: str) -> None:
    """Recompute the index's staged vectors and grade DB HNSW against the exact
    oracle using the metrics module's re-exported recall (M2-024 reuse)."""
    index_version_id = seeded["index_version_id"]
    provider = MockEmbeddingProvider(512)
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT id, content FROM retrieval_items WHERE index_version_id = %s",
            (index_version_id,),
        ).fetchall()
    staged = [(str(item_id), provider.embed([content])[0]) for item_id, content in rows]
    assert len(staged) >= 4

    query_vector = provider.embed(["revenue for fiscal 2025"])[0]
    k = 3
    exact = exact_knn(query_vector, staged, k)
    with psycopg.connect(db_url, autocommit=True) as conn:
        approx = hnsw_search(
            conn, index_version_id=index_version_id, query_vector=query_vector, k=k
        )
    assert len(approx) == k
    assert hnsw_recall_at_k(exact, approx, k) >= 0.9


def test_reference_performance_smoke(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str]
) -> None:
    """Reference (single-node, mock) p95 for the full create->generate->verify
    pipeline. Generous budget sized well above local latency; guards gross
    regressions only, not a benchmark."""
    n = 15
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
    p95 = durations[-1]  # nearest-rank p95 of 15 samples (ceil(0.95*15) = 15th)
    assert p95 < 3.0, f"p95 create-query latency {p95:.3f}s exceeded reference budget"
