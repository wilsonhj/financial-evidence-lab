"""Unit tests for M2-014 lane fusion (RRF, dedupe, rerank hook, determinism)."""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from fel_retrieval.fusion import (
    RERANK_TOP_N,
    RRF_K,
    FusedCandidate,
    LaneExecutionError,
    NoopReranker,
    execute_lanes,
    fuse,
)
from fel_retrieval.lanes import (
    LANE_DENSE,
    LANE_FACTS,
    LANE_LEXICAL,
    LANE_TABLES,
    LaneCandidate,
)

_PUBLISHED = datetime(2025, 1, 1, tzinfo=UTC)


def _cand(
    item_id: str,
    lane: str,
    lane_rank: int,
    *,
    kind: str = "passage",
    source_span_id: str | None = None,
    financial_fact_id: str | None = None,
    table_id: str | None = None,
    table_row_index: int | None = None,
) -> LaneCandidate:
    return LaneCandidate(
        item_id=item_id,
        lane=lane,
        lane_rank=lane_rank,
        raw_score=f"{1.0 / lane_rank:.6f}",
        kind=kind,
        source_span_id=source_span_id if source_span_id is not None else f"span-{item_id}",
        document_version_id="dv-1",
        document_id="doc-1",
        published_at=_PUBLISHED,
        financial_fact_id=financial_fact_id,
        table_id=table_id,
        table_row_index=table_row_index,
    )


# --- RRF math --------------------------------------------------------------
def test_rrf_math_exact_hand_computed() -> None:
    # A appears dense#1 + lexical#2; B appears dense#2. k=60.
    lane_results = {
        LANE_DENSE: [_cand("A", LANE_DENSE, 1), _cand("B", LANE_DENSE, 2)],
        LANE_LEXICAL: [_cand("A", LANE_LEXICAL, 2)],
    }
    result = fuse(lane_results, fused_top_k=10)
    cands = {c.item_id: c for c in result.candidates}

    # 1/(60+1)=0.016393442623, 1/(60+2)=0.016129032258 (12dp, ROUND_HALF_EVEN).
    assert cands["A"].fused_score == "0.032522474881"
    assert cands["B"].fused_score == "0.016129032258"
    # A outranks B and carries both lane contributions in LANE_ORDER.
    assert [c.item_id for c in result.candidates] == ["A", "B"]
    assert cands["A"].fused_rank == 1 and cands["B"].fused_rank == 2
    assert [c.lane for c in cands["A"].contributions] == [LANE_DENSE, LANE_LEXICAL]
    assert cands["A"].contributions[0].rrf_contribution == "0.016393442623"
    assert cands["A"].contributions[1].rrf_contribution == "0.016129032258"


def test_rrf_constant_is_sixty() -> None:
    assert RRF_K == 60


def test_rrf_tie_break_is_item_id_ascending() -> None:
    # Equal RRF (both single dense#1); ascending item id wins the tie.
    lane_results = {LANE_DENSE: [_cand("zzz", LANE_DENSE, 1), _cand("aaa", LANE_DENSE, 1)]}
    result = fuse(lane_results, fused_top_k=10)
    assert [c.item_id for c in result.candidates] == ["aaa", "zzz"]
    assert result.candidates[0].fused_score == result.candidates[1].fused_score


# --- Dedupe ----------------------------------------------------------------
def test_dedupe_survivor_is_best_rank() -> None:
    # Two distinct items on the SAME span; best (lowest) rank survives.
    span = "shared-span"
    lane_results = {
        LANE_DENSE: [_cand("winner", LANE_DENSE, 1, source_span_id=span)],
        LANE_LEXICAL: [_cand("loser", LANE_LEXICAL, 3, source_span_id=span)],
    }
    result = fuse(lane_results, fused_top_k=10)
    assert [c.item_id for c in result.candidates] == ["winner"]
    dedupe = [d for d in result.decisions if d.stage == "dedupe"]
    assert len(dedupe) == 1
    assert dedupe[0].code == "provenance_merge"
    assert dedupe[0].detail["survivor"] == "winner"
    assert dedupe[0].detail["merged"] == ["loser"]
    assert set(dedupe[0].item_ids) == {"winner", "loser"}


def test_dedupe_tie_breaks_on_item_id() -> None:
    # Same span, both best rank 1 -> lowest item id survives.
    span = "tie-span"
    lane_results = {
        LANE_DENSE: [_cand("bbb", LANE_DENSE, 1, source_span_id=span)],
        LANE_LEXICAL: [_cand("aaa", LANE_LEXICAL, 1, source_span_id=span)],
    }
    result = fuse(lane_results, fused_top_k=10)
    assert [c.item_id for c in result.candidates] == ["aaa"]


def test_dedupe_provenance_by_fact_and_table() -> None:
    # Distinct items sharing a fact id (and another pair sharing a table row) merge.
    lane_results = {
        LANE_FACTS: [
            _cand("f1", LANE_FACTS, 1, kind="fact", financial_fact_id="fact-X"),
            _cand("f2", LANE_FACTS, 2, kind="fact", financial_fact_id="fact-X"),
        ],
        LANE_TABLES: [
            _cand("t1", LANE_TABLES, 1, kind="table_row", table_id="tab-Y", table_row_index=3),
            _cand("t2", LANE_TABLES, 5, kind="table_row", table_id="tab-Y", table_row_index=3),
        ],
    }
    result = fuse(lane_results, fused_top_k=10)
    survivors = {c.item_id for c in result.candidates}
    assert survivors == {"f1", "t1"}
    assert len([d for d in result.decisions if d.stage == "dedupe"]) == 2


def test_distinct_provenance_not_merged() -> None:
    lane_results = {
        LANE_DENSE: [_cand("A", LANE_DENSE, 1), _cand("B", LANE_DENSE, 2)],
    }
    result = fuse(lane_results, fused_top_k=10)
    assert {c.item_id for c in result.candidates} == {"A", "B"}
    assert [d for d in result.decisions if d.stage == "dedupe"] == []


# --- Reranker hook ---------------------------------------------------------
class _SpyReranker:
    name = "spy"

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.top_n: int | None = None

    def rerank(
        self, candidates: Sequence[FusedCandidate], *, top_n: int
    ) -> Sequence[FusedCandidate]:
        self.seen = [c.item_id for c in candidates]
        self.top_n = top_n
        return list(candidates)


def test_rerank_hook_sees_top_100_only() -> None:
    # 105 distinct dense candidates -> hook sees exactly the top 100.
    dense = [_cand(f"i{n:03d}", LANE_DENSE, rank) for rank, n in enumerate(range(105), start=1)]
    spy = _SpyReranker()
    result = fuse({LANE_DENSE: dense}, fused_top_k=100, reranker=spy)
    assert spy.top_n == RERANK_TOP_N == 100
    assert len(spy.seen) == 100
    # Top 100 by fused order (rank ascending = i000..i099).
    assert spy.seen == [f"i{n:03d}" for n in range(100)]
    rerank = [d for d in result.decisions if d.stage == "rerank"]
    assert len(rerank) == 1
    assert rerank[0].code == "spy"
    assert len(rerank[0].item_ids) == 100


def test_noop_reranker_preserves_order_and_records_decision() -> None:
    lane_results = {LANE_DENSE: [_cand("A", LANE_DENSE, 1), _cand("B", LANE_DENSE, 2)]}
    result = fuse(lane_results, fused_top_k=10, reranker=NoopReranker())
    assert [c.item_id for c in result.candidates] == ["A", "B"]
    rerank = [d for d in result.decisions if d.stage == "rerank"]
    assert len(rerank) == 1 and rerank[0].code == "noop"
    assert rerank[0].item_ids == ("A", "B")


def test_default_reranker_is_noop() -> None:
    result = fuse({LANE_DENSE: [_cand("A", LANE_DENSE, 1)]}, fused_top_k=10)
    rerank = [d for d in result.decisions if d.stage == "rerank"]
    assert rerank[0].code == "noop"


# --- Budgets ---------------------------------------------------------------
def test_budget_truncates_to_fused_top_k() -> None:
    dense = [_cand(f"i{n}", LANE_DENSE, rank) for rank, n in enumerate(range(5), start=1)]
    result = fuse({LANE_DENSE: dense}, fused_top_k=2)
    assert len(result.candidates) == 2
    assert [c.item_id for c in result.candidates] == ["i0", "i1"]
    # Fusion decision still lists the full fused set before truncation.
    fusion = [d for d in result.decisions if d.stage == "fusion"][0]
    assert len(fusion.item_ids) == 5


# --- Lane failure ----------------------------------------------------------
def test_lane_failure_fails_closed() -> None:
    def ok() -> list[LaneCandidate]:
        return [_cand("A", LANE_DENSE, 1)]

    def boom() -> list[LaneCandidate]:
        raise RuntimeError("db exploded")

    with pytest.raises(LaneExecutionError) as excinfo:
        execute_lanes([(LANE_DENSE, ok), (LANE_LEXICAL, boom)])
    assert excinfo.value.lane == LANE_LEXICAL
    assert isinstance(excinfo.value.__cause__, RuntimeError)


# --- Determinism -----------------------------------------------------------
def _mixed_lane_results() -> dict[str, list[LaneCandidate]]:
    return {
        LANE_DENSE: [
            _cand("A", LANE_DENSE, 1),
            _cand("B", LANE_DENSE, 2),
            _cand("C", LANE_DENSE, 3),
        ],
        LANE_LEXICAL: [_cand("B", LANE_LEXICAL, 1), _cand("A", LANE_LEXICAL, 2)],
        LANE_FACTS: [_cand("D", LANE_FACTS, 1, kind="fact", financial_fact_id="fact-D")],
        LANE_TABLES: [
            _cand("E", LANE_TABLES, 1, kind="table_row", table_id="tab-E", table_row_index=0)
        ],
    }


def test_fusion_is_byte_identical_across_runs() -> None:
    lane_results = _mixed_lane_results()
    first = fuse(lane_results, fused_top_k=100).to_canonical_json()
    second = fuse(lane_results, fused_top_k=100).to_canonical_json()
    assert first == second


def test_fusion_is_invariant_to_input_order() -> None:
    lane_results = _mixed_lane_results()
    baseline = fuse(lane_results, fused_top_k=100).to_canonical_json()

    rng = random.Random(1234)
    for _ in range(8):
        shuffled_lanes = list(lane_results.items())
        rng.shuffle(shuffled_lanes)
        shuffled = {}
        for lane, cands in shuffled_lanes:
            copied = list(cands)
            rng.shuffle(copied)
            shuffled[lane] = copied
        assert fuse(dict(shuffled), fused_top_k=100).to_canonical_json() == baseline


def test_occurred_at_injection_does_not_change_candidate_order() -> None:
    lane_results = _mixed_lane_results()
    stamped = fuse(lane_results, fused_top_k=100, now=lambda: "2026-07-17T00:00:00Z")
    plain = fuse(lane_results, fused_top_k=100)
    # occurred_at is excluded from the canonical form, so both serialize identically.
    assert stamped.to_canonical_json() == plain.to_canonical_json()
    assert all(d.occurred_at == "2026-07-17T00:00:00Z" for d in stamped.decisions)
    assert all(d.occurred_at is None for d in plain.decisions)


# --- Concurrency smoke -----------------------------------------------------
def test_concurrent_execution_matches_sequential() -> None:
    def make_call(lane: str, cands: list[LaneCandidate]) -> object:
        def call() -> list[LaneCandidate]:
            time.sleep(0.01)  # force thread interleaving
            return cands

        return call

    lane_results = _mixed_lane_results()
    calls = [(lane, make_call(lane, cands)) for lane, cands in lane_results.items()]

    concurrent = execute_lanes(calls)  # type: ignore[arg-type]
    assert set(concurrent) == set(lane_results)

    fused_concurrent = fuse(concurrent, fused_top_k=100).to_canonical_json()
    fused_sequential = fuse(lane_results, fused_top_k=100).to_canonical_json()
    assert fused_concurrent == fused_sequential
