"""M2-024 smoke gate: measured metrics, per-lane ablations, exact-vs-HNSW recall,
release-gate report and a reference-performance smoke.

These run the real retrieval pipeline over a small seeded, indexed corpus (mock
providers) and grade it with ``fel_retrieval_evals.metrics``. On this controlled
corpus every gate metric is perfect, so the smoke asserts the thresholds hold and
the ADR-0002 reranker stays disabled (report-only). They skip cleanly when
TEST_DATABASE_URL is unset.
"""

from __future__ import annotations

import re
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
    SMOKE_THRESHOLDS,
    QuestionOutcome,
    aggregate_metrics,
    build_gate_report,
    hnsw_recall_at_k,
    metric_supports,
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


def _content_by_item(db_url: str, index_version_id: str) -> dict[str, str]:
    """The persisted span text of every retrieval item in the index, by item id."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT id, content FROM retrieval_items WHERE index_version_id = %s",
            (index_version_id,),
        ).fetchall()
    return {str(r[0]): r[1] for r in rows}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _grounded(claim_text: str, span_text: str) -> bool:
    """Whether a claim is truly supported by a cited span's persisted text.

    A supporting edge is only *correct* if the claim it grounds is covered by the
    span the pipeline actually persisted for that citation. This is the honest
    entailment check the smoke grades against, so a hallucinated supporting edge
    (a claim citing a span whose text does not support it) is not counted.
    """
    claim = _tokens(claim_text)
    return bool(claim) and claim <= _tokens(span_text)


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

    # Grade the run's claims/citations. A supporting edge only counts as correct
    # when the claim it grounds is actually covered by the span the pipeline
    # persisted for that citation -- so a hallucinated supporting edge would drop
    # entailment precision rather than be waved through.
    content_by_item = _content_by_item(db_url, seeded["index_version_id"])
    as_of_iso = _AS_OF.isoformat()
    temporal_ok = all(c["published_at"] <= as_of_iso for c in trace["candidates"])
    supporting = correct = rendered = cited = 0
    numeric_expected = False
    numeric_correct = True
    for claim in trace["claims"]:
        if claim["status"] in {"supported", "derived"}:
            rendered += 1
            if claim["citations"]:
                cited += 1
        for citation in claim["citations"]:
            if citation["status"] in {"entailed", "partial"}:
                supporting += 1
                if _grounded(claim["text"], content_by_item.get(citation["item_id"], "")):
                    correct += 1
            if citation["numeric_checks"]:
                numeric_expected = True
                # AND across citations — last-write-wins would drop earlier failures.
                numeric_correct = numeric_correct and all(citation["numeric_checks"].values())

    assert supporting > 0 and correct == supporting, "seeded edges must all be grounded"
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
    metrics = aggregate_metrics([outcome])
    # Controlled smoke corpus: every gate metric is exact Decimal(1).
    for name in SMOKE_THRESHOLDS:
        assert metrics[name] == Decimal(1), f"{name}={metrics[name]}"
    report = build_gate_report(metrics, supports=metric_supports([outcome]))
    assert report.passed, report.to_dict()
    assert report.reranker_triggered is False
    assert numeric_expected, "expected a fact-backed numeric claim on the seed corpus"


def test_smoke_numeric_correct_ands_across_citations() -> None:
    """Regression: an earlier failing numeric citation must not be overwritten by
    a later passing one (last-write-wins would falsely report numeric_correct)."""
    # Two numeric citations: first fails value, second passes all — AND is False.
    citations = [
        {"status": "entailed", "numeric_checks": {"value": False, "unit": True}},
        {"status": "entailed", "numeric_checks": {"value": True, "unit": True}},
    ]
    numeric_expected = False
    numeric_correct = True
    for citation in citations:
        if citation["numeric_checks"]:
            numeric_expected = True
            numeric_correct = numeric_correct and all(citation["numeric_checks"].values())
    assert numeric_expected is True
    assert numeric_correct is False

    # Last-write-wins (the old bug) would have kept only the final True.
    last_write = True
    for citation in citations:
        if citation["numeric_checks"]:
            last_write = all(citation["numeric_checks"].values())
    assert last_write is True, "precondition: last-write-wins would wrongly pass"


def test_smoke_entailment_catches_hallucinated_supporting_edge(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    """Inject a supporting edge whose cited span does NOT support the claim and
    confirm the smoke's entailment grading catches it: precision drops below the
    0.95 threshold and the gate fails closed. Guards against a tautological
    ``correct += 1`` that could never see a hallucination."""
    created = _create(client, org, seeded["workspace_id"])
    trace = _trace(client, org, created["run_id"])
    content_by_item = _content_by_item(db_url, seeded["index_version_id"])

    # A real supported claim and a span from a DIFFERENT sentence that cannot
    # ground it (persisted corpus text, not a synthetic string). The span is
    # chosen by raw token overlap so this selection never depends on the grading
    # function under test.
    claim = next(c for c in trace["claims"] if c["status"] in {"supported", "derived"})
    cited_ids = {cit["item_id"] for cit in claim["citations"]}
    claim_tokens = _tokens(claim["text"])
    bogus_item, bogus_text = min(
        ((iid, text) for iid, text in content_by_item.items() if iid not in cited_ids),
        key=lambda it: len(claim_tokens & _tokens(it[1])),
    )
    # Precondition: the claim really is not covered by this span (uncounted edge).
    assert claim_tokens - _tokens(bogus_text), "chosen span unexpectedly grounds the claim"

    # Grade the genuine edges, then add one hallucinated supporting edge.
    supporting = correct = rendered = cited = 0
    for c in trace["claims"]:
        if c["status"] in {"supported", "derived"}:
            rendered += 1
            if c["citations"]:
                cited += 1
        for citation in c["citations"]:
            if citation["status"] in {"entailed", "partial"}:
                supporting += 1
                if _grounded(c["text"], content_by_item.get(citation["item_id"], "")):
                    correct += 1
    supporting += 1  # hallucinated supporting edge asserted by the run
    if _grounded(claim["text"], bogus_text):  # must NOT count -- span cannot ground it
        correct += 1
    assert bogus_item  # a non-supporting span existed to inject

    outcome = QuestionOutcome(
        recall_at_10=Decimal(1),
        temporal_ok=True,
        supporting_citations=supporting,
        correct_supporting_citations=correct,
        rendered_claims=rendered,
        cited_rendered_claims=cited,
    )
    report = build_gate_report(aggregate_metrics([outcome]), supports=metric_supports([outcome]))
    entailment = next(r for r in report.results if r.name == "entailment_precision")
    assert entailment.value < SMOKE_THRESHOLDS["entailment_precision"]
    assert not report.passed


def test_per_lane_ablation(
    client: TestClient, org: tuple[str, str], seeded: dict[str, str], db_url: str
) -> None:
    gold = _gold_revenue_items(db_url, seeded["index_version_id"])

    def run(lanes: list[str]) -> tuple[set[str], Decimal]:
        created = _create(client, org, seeded["workspace_id"], lanes=lanes)
        trace = _trace(client, org, created["run_id"])
        candidates = {c["item_id"] for c in trace["candidates"]}
        return candidates, question_recall_at_k(_top_items(trace, 10), gold, 10)

    full_candidates, full_recall = run(_LANES)
    shrunk = False
    for lane in _LANES:
        candidates, recall = run([x for x in _LANES if x != lane])
        # Dropping a lane can only remove candidates, never add or improve recall.
        assert recall <= full_recall, f"ablating {lane} raised recall ({recall} > {full_recall})"
        assert candidates <= full_candidates, f"ablating {lane} introduced new candidates"
        if candidates < full_candidates:
            shrunk = True
    # Isolation, not mere monotonicity: at least one lane must contribute
    # candidates no other lane does, so dropping it strictly shrinks the set. If
    # lane selection were a silent no-op every ablation would return the full set
    # and this would fail.
    assert shrunk, "no lane ablation reduced the candidate set; lane selection may be a no-op"


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
