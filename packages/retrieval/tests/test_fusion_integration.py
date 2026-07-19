"""End-to-end plan -> concurrent lanes -> fusion against pgvector (M2-014).

Seeds one immutable corpus, builds/publishes an index over it, then runs the
four lanes concurrently (each on its own connection) and fuses them. Asserts the
fused ordering is deterministic across two runs and every fused candidate carries
at least one lane contribution. Skips cleanly when TEST_DATABASE_URL is unset.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from fel_retrieval import (
    FusionResult,
    LaneQuery,
    build_index,
    dense_lane,
    execute_lanes,
    facts_lane,
    fuse,
    lexical_lane,
    make_index_version_spec,
    publish_index_version,
    tables_lane,
)
from fel_retrieval.fusion import LaneCall
from fel_retrieval.lanes import LANE_DENSE, LANE_FACTS, LANE_LEXICAL, LANE_TABLES, LaneCandidate

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - psycopg is a dev dependency
    psycopg = None  # type: ignore[assignment]

from fel_providers import MockEmbeddingProvider

PROVIDER = "mock"
MODEL = "mock-embed-v1"
WIDE_CUTOFF = datetime(2099, 1, 1, tzinfo=UTC)
QUERY_TEXT = "revenue or income or sales or assets in fiscal 2025"

LaneFn = Callable[[Any, LaneQuery], list[LaneCandidate]]


def _build_query(conn: Any, seed_corpus: Callable[[], Any]) -> LaneQuery:
    seeded = seed_corpus()
    spec = make_index_version_spec(
        corpus_version_id=seeded.corpus_version_id,
        embedding_provider=PROVIDER,
        embedding_model=MODEL,
    )
    build_index(conn, spec=spec, corpus=seeded.corpus, provider=MockEmbeddingProvider(512))
    publish_index_version(conn, spec.id, activate=False)
    vector = MockEmbeddingProvider(512).embed([QUERY_TEXT])[0]
    return LaneQuery(
        index_version_id=spec.id,
        as_of=WIDE_CUTOFF,
        query_text=QUERY_TEXT,
        query_vector=vector,
        corpus_version_id=seeded.corpus_version_id,
    )


def _run_pipeline(query: LaneQuery) -> FusionResult:
    """Run the four lanes concurrently, each on its own connection, then fuse."""
    url = os.environ["TEST_DATABASE_URL"]

    def make_call(lane_fn: LaneFn) -> LaneCall:
        def call() -> list[LaneCandidate]:
            assert psycopg is not None
            with psycopg.connect(url, autocommit=True) as conn:
                return lane_fn(conn, query)

        return call

    lane_calls: list[tuple[str, LaneCall]] = [
        (LANE_DENSE, make_call(dense_lane)),
        (LANE_LEXICAL, make_call(lexical_lane)),
        (LANE_FACTS, make_call(facts_lane)),
        (LANE_TABLES, make_call(tables_lane)),
    ]
    lane_results = execute_lanes(lane_calls)
    return fuse(lane_results, fused_top_k=100)


@pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None or psycopg is None,
    reason="TEST_DATABASE_URL not configured (needs pgvector Postgres)",
)
def test_full_pipeline_is_deterministic_and_traceable(
    pg_conn: Any, seed_corpus: Callable[[], Any]
) -> None:
    query = _build_query(pg_conn, seed_corpus)

    first = _run_pipeline(query)
    second = _run_pipeline(query)

    assert first.candidates, "fusion returned no candidates"
    # Deterministic across two independent concurrent runs.
    assert first.to_canonical_json() == second.to_canonical_json()
    # Every fused candidate is backed by at least one lane contribution.
    for cand in first.candidates:
        assert len(cand.contributions) >= 1
    # The trace records the fusion and rerank stages.
    stages = {d.stage for d in first.decisions}
    assert {"fusion", "rerank"} <= stages
