"""DB-less coverage of lane SQL construction via a recording fake connection.

Asserts every lane carries the pin/cutoff/filter predicates and deterministic
ordering, and that values travel as parameters (never interpolated). The
behaviour against Postgres is exercised in test_lanes_integration.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fel_retrieval import (
    LaneQuery,
    dense_lane,
    facts_lane,
    lexical_lane,
    tables_lane,
)

AS_OF = datetime(2025, 6, 30, tzinfo=UTC)
INDEX_ID = "11111111-1111-4111-8111-111111111111"


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeConn:
    """Records executed statements; returns a scripted result for the SELECT."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._rows = rows or []

    def execute(self, query: str, params: Any = None) -> FakeCursor:
        self.calls.append((" ".join(query.split()), params))
        stripped = " ".join(query.split())
        if stripped.startswith("SET"):
            return FakeCursor([])
        return FakeCursor(self._rows)

    def select_call(self) -> tuple[str, Any]:
        for sql, params in self.calls:
            if "SELECT" in sql and "FROM retrieval_" in sql:
                return sql, params
        raise AssertionError("no lane SELECT recorded")


def _vector() -> list[float]:
    return [0.1] * 512


def _base_query(**overrides: Any) -> LaneQuery:
    defaults: dict[str, Any] = {
        "index_version_id": INDEX_ID,
        "as_of": AS_OF,
        "query_text": "operating income fiscal 2025",
        "query_vector": _vector(),
    }
    defaults.update(overrides)
    return LaneQuery(**defaults)


def test_dense_lane_pins_index_and_cutoff() -> None:
    conn = FakeConn()
    dense_lane(conn, _base_query())
    sql, params = conn.select_call()
    # Pin + cutoff predicates present and parameterized.
    assert "ri.index_version_id = %s" in sql
    assert "d.published_at <= %s" in sql
    # Composite-FK-consistent join keeps rows inside the pinned index.
    assert "ri.index_version_id = re.index_version_id" in sql
    assert "ri.content_sha256 = re.content_sha256" in sql
    # Deterministic ordering with a stable id tie-break.
    assert "ORDER BY distance ASC, ri.id ASC" in sql
    # Pinned index id and cutoff travel as bound params (no interpolation).
    assert INDEX_ID in params
    assert AS_OF in params


def test_dense_lane_requires_vector() -> None:
    with pytest.raises(ValueError, match="query_vector"):
        dense_lane(FakeConn(), _base_query(query_vector=None))


def test_dense_lane_sets_iterative_scan() -> None:
    conn = FakeConn()
    dense_lane(conn, _base_query())
    set_calls = [sql for sql, _ in conn.calls if sql.startswith("SET")]
    assert any("hnsw.iterative_scan = relaxed_order" in c for c in set_calls)
    assert any("hnsw.ef_search" in c for c in set_calls)


@pytest.mark.parametrize(
    "lane_fn, expected_kind",
    [(lexical_lane, None), (facts_lane, "fact"), (tables_lane, "table_row")],
)
def test_fts_lane_pins_cutoff_and_kind(lane_fn: Any, expected_kind: str | None) -> None:
    conn = FakeConn()
    lane_fn(conn, _base_query())
    sql, params = conn.select_call()
    assert "ri.index_version_id = %s" in sql
    assert "d.published_at <= %s" in sql
    assert "ri.search_vector @@ q.query" in sql
    assert "ORDER BY score DESC, ri.id ASC" in sql
    assert INDEX_ID in params
    assert AS_OF in params
    if expected_kind is None:
        assert "ri.kind = %s" not in sql
    else:
        assert "ri.kind = %s" in sql
        assert expected_kind in params


def test_filters_pushed_into_sql_as_params() -> None:
    conn = FakeConn()
    query = _base_query(
        entity_id="22222222-2222-4222-8222-222222222222",
        document_ids=("33333333-3333-4333-8333-333333333333",),
        forms=("10-K",),
        periods=("FY2025",),
        corpus_version_id="44444444-4444-4444-8444-444444444444",
    )
    lexical_lane(conn, query)
    sql, params = conn.select_call()
    assert "ri.entity_id = %s" in sql
    assert "ri.document_id = ANY(%s)" in sql
    assert "ri.form = ANY(%s)" in sql
    assert "ri.period = ANY(%s)" in sql
    assert "corpus_version_documents" in sql
    assert query.entity_id in params
    assert ["10-K"] in params
    assert ["FY2025"] in params
    assert query.corpus_version_id in params


def test_omitted_filters_absent_from_sql() -> None:
    conn = FakeConn()
    lexical_lane(conn, _base_query())
    sql, _ = conn.select_call()
    assert "ri.entity_id" not in sql
    assert "ri.form" not in sql
    assert "ri.period" not in sql
    assert "corpus_version_documents" not in sql


def test_facts_lane_maps_financial_fact_provenance() -> None:
    row = (
        "item-1",
        "fact",
        "span-1",
        "dv-1",
        "doc-1",
        AS_OF,
        "fact-9",  # financial_fact_id
        None,
        None,
        0.5,  # score
    )
    conn = FakeConn(rows=[row])
    [candidate] = facts_lane(conn, _base_query())
    assert candidate.lane == "facts"
    assert candidate.lane_rank == 1
    assert candidate.kind == "fact"
    assert candidate.financial_fact_id == "fact-9"
    assert candidate.table_id is None
    assert candidate.raw_score == "0.500000"


def test_tables_lane_maps_table_provenance() -> None:
    row = (
        "item-2",
        "table_row",
        "span-2",
        "dv-1",
        "doc-1",
        AS_OF,
        None,
        "table-7",  # table_id
        3,  # table_row_index
        0.25,
    )
    conn = FakeConn(rows=[row])
    [candidate] = tables_lane(conn, _base_query())
    assert candidate.lane == "tables"
    assert candidate.table_id == "table-7"
    assert candidate.table_row_index == 3
    assert candidate.financial_fact_id is None


def test_dense_lane_ranks_and_scores_by_similarity() -> None:
    rows = [
        ("item-a", "passage", "span-a", "dv-1", "doc-1", AS_OF, None, None, None, 0.1),
        ("item-b", "passage", "span-b", "dv-1", "doc-1", AS_OF, None, None, None, 0.4),
    ]
    conn = FakeConn(rows=rows)
    candidates = dense_lane(conn, _base_query())
    assert [c.lane_rank for c in candidates] == [1, 2]
    # similarity = 1 - distance
    assert candidates[0].raw_score == "0.900000"
    assert candidates[1].raw_score == "0.600000"
