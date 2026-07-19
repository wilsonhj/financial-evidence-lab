"""Cutoff-safe pinned retrieval lanes (M2-012 / T0203).

Four lanes retrieve per-lane candidates from the shared, immutable retrieval
tables (ADR-0006): ``dense`` (halfvec cosine HNSW), ``lexical`` (English FTS
over ``search_vector``), ``facts`` (FTS restricted to ``kind='fact'`` items,
mapped to ``financial_fact`` provenance) and ``tables`` (FTS restricted to
``kind='table_row'`` items, mapped to ``(table_id, table_row_index)``).

Every lane enforces the same fail-closed guards, so no lane can surface
evidence a downstream candidate insert would reject
(``fel_guard_candidate`` in ``0003_retrieval_core.sql``):

* **Index pin.** Every row is filtered by the pinned ``index_version_id`` and
  all item joins stay composite-FK-consistent with that pin — the dense lane
  joins ``retrieval_embeddings`` to ``retrieval_items`` on
  ``(id, index_version_id, content_sha256)``, the exact tuple the schema's
  foreign key uses, so cross-index rows can never join through.
* **Cutoff.** Candidates are restricted to ``documents.published_at <= as_of``
  (the same column ``fel_guard_candidate`` checks). Anything published after
  the cutoff is dropped; omitting the predicate would let cross-cutoff
  evidence leak, so it is always present.
* **Corpus pin.** When a ``corpus_version_id`` is supplied, rows are further
  restricted to document versions listed in that corpus version.
* **Filters.** Entity, document, form and period filters are pushed into SQL
  against the denormalized ``form``/``period`` columns and their B-tree
  indexes.

Runtime code is driver-agnostic (injected DB-API/psycopg connection, standard
library only) and uses parameterized SQL exclusively — values are never
interpolated into query text. Ordering is deterministic: each lane sorts by
its score then ``id`` ascending as a stable tie-break, so identical inputs
yield identical candidate lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fel_retrieval.embeddings import format_halfvec
from fel_retrieval.index_build import DBConnection

# Contract lane names (openapi CandidateContribution.lane / retrieval_candidates
# CHECK). Kept as constants so callers and tests share one source of truth.
LANE_DENSE = "dense"
LANE_LEXICAL = "lexical"
LANE_FACTS = "facts"
LANE_TABLES = "tables"

_DEFAULT_TOP_K = 100


@dataclass(frozen=True)
class LaneQuery:
    """Pinned, cutoff-bound inputs shared by every lane.

    ``query_vector`` is required by the dense lane; ``query_text`` by the
    lexical/facts/tables lanes. Filters are optional and, when present, pushed
    into SQL.
    """

    index_version_id: str
    as_of: datetime
    query_text: str = ""
    query_vector: Any = None
    entity_id: str | None = None
    document_ids: tuple[str, ...] | None = None
    forms: tuple[str, ...] | None = None
    periods: tuple[str, ...] | None = None
    corpus_version_id: str | None = None
    top_k: int = _DEFAULT_TOP_K


@dataclass(frozen=True)
class LaneCandidate:
    """One per-lane hit with the provenance the candidate contract needs."""

    item_id: str
    lane: str
    lane_rank: int
    raw_score: str
    kind: str
    source_span_id: str
    document_version_id: str
    document_id: str
    published_at: datetime
    financial_fact_id: str | None = None
    table_id: str | None = None
    table_row_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Provenance columns selected by every lane, in a fixed order the row mapper
# below relies on.
_PROVENANCE_COLUMNS = (
    "ri.id",
    "ri.kind",
    "ri.source_span_id",
    "ri.document_version_id",
    "ri.document_id",
    "d.published_at",
    "ri.financial_fact_id",
    "ri.table_id",
    "ri.table_row_index",
)
# Fixed projection list; assembled once from code-controlled column names so
# query construction never formats/interpolates a runtime value into SQL text.
_COLUMNS_SQL = ", ".join(_PROVENANCE_COLUMNS)


def _score_str(value: float) -> str:
    """Fixed-precision decimal string matching the raw_score CHECK pattern."""
    return f"{value:.6f}"


def _filter_clauses(query: LaneQuery, *, kind: str | None) -> tuple[list[str], list[Any]]:
    """Shared pin + cutoff + filter predicates (parameterized).

    Returns SQL fragments joined by the caller with ``AND`` and the matching
    positional parameters. The index pin and cutoff are unconditional so the
    lane always fails closed.
    """
    clauses: list[str] = [
        "ri.index_version_id = %s",
        "d.published_at <= %s",
    ]
    params: list[Any] = [query.index_version_id, query.as_of]

    if kind is not None:
        clauses.append("ri.kind = %s")
        params.append(kind)
    if query.entity_id is not None:
        clauses.append("ri.entity_id = %s")
        params.append(query.entity_id)
    if query.document_ids is not None:
        clauses.append("ri.document_id = ANY(%s)")
        params.append(list(query.document_ids))
    if query.forms is not None:
        clauses.append("ri.form = ANY(%s)")
        params.append(list(query.forms))
    if query.periods is not None:
        clauses.append("ri.period = ANY(%s)")
        params.append(list(query.periods))
    if query.corpus_version_id is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM corpus_version_documents cvd "
            "WHERE cvd.corpus_version_id = %s "
            "AND cvd.document_version_id = ri.document_version_id)"
        )
        params.append(query.corpus_version_id)
    return clauses, params


def _row_to_candidate(
    row: tuple[Any, ...], *, lane: str, lane_rank: int, score: str
) -> LaneCandidate:
    (
        item_id,
        kind,
        source_span_id,
        document_version_id,
        document_id,
        published_at,
        financial_fact_id,
        table_id,
        table_row_index,
    ) = row
    return LaneCandidate(
        item_id=str(item_id),
        lane=lane,
        lane_rank=lane_rank,
        raw_score=score,
        kind=str(kind),
        source_span_id=str(source_span_id),
        document_version_id=str(document_version_id),
        document_id=str(document_id),
        published_at=published_at,
        financial_fact_id=None if financial_fact_id is None else str(financial_fact_id),
        table_id=None if table_id is None else str(table_id),
        table_row_index=None if table_row_index is None else int(table_row_index),
    )


def dense_lane(conn: DBConnection, query: LaneQuery) -> list[LaneCandidate]:
    """Cosine HNSW dense lane over the pinned index's embeddings.

    Joins embeddings to items on the schema's composite key so the pin holds
    through the join, applies cutoff/entity/document/form/period/corpus
    filters, and orders by cosine distance ascending with ``id`` as a stable
    tie-break. ``iterative_scan=relaxed_order`` keeps filtered top-k recall
    stable (ADR-0006).
    """
    if query.query_vector is None:
        raise ValueError("dense_lane requires query.query_vector")
    conn.execute("SET hnsw.ef_search = 100")
    conn.execute("SET hnsw.iterative_scan = relaxed_order")

    clauses, params = _filter_clauses(query, kind=None)
    # Assembled purely from code-controlled fragments (no value interpolation);
    # every runtime value below travels as a bound %s parameter.
    sql = " ".join(
        [
            "WITH v AS (SELECT %s::halfvec(512) AS qv)",
            "SELECT",
            _COLUMNS_SQL,
            ", (re.embedding <=> v.qv) AS distance",
            "FROM retrieval_embeddings re",
            "JOIN retrieval_items ri",
            "ON ri.id = re.retrieval_item_id",
            "AND ri.index_version_id = re.index_version_id",
            "AND ri.content_sha256 = re.content_sha256",
            "JOIN documents d ON d.id = ri.document_id",
            "CROSS JOIN v",
            "WHERE",
            " AND ".join(clauses),
            "ORDER BY distance ASC, ri.id ASC",
            "LIMIT %s",
        ]
    )
    exec_params = [format_halfvec(query.query_vector), *params, query.top_k]
    rows = conn.execute(sql, tuple(exec_params)).fetchall()
    candidates: list[LaneCandidate] = []
    for rank, row in enumerate(rows, start=1):
        distance = float(row[-1])
        candidates.append(
            _row_to_candidate(
                row[:-1], lane=LANE_DENSE, lane_rank=rank, score=_score_str(1.0 - distance)
            )
        )
    return candidates


def _fts_lane(
    conn: DBConnection, query: LaneQuery, *, lane: str, kind: str | None
) -> list[LaneCandidate]:
    """Shared English-FTS lane body (lexical/facts/tables).

    ``kind`` narrows to a single item kind for the structured lanes; ``None``
    (lexical) spans all kinds. Ranks by ``ts_rank_cd`` descending with ``id``
    as a stable tie-break.
    """
    clauses, params = _filter_clauses(query, kind=kind)
    # Assembled purely from code-controlled fragments (no value interpolation);
    # the query text and every filter value travel as bound %s parameters.
    sql = " ".join(
        [
            "WITH q AS (SELECT websearch_to_tsquery('english', %s) AS query)",
            "SELECT",
            _COLUMNS_SQL,
            ", ts_rank_cd(ri.search_vector, q.query) AS score",
            "FROM retrieval_items ri",
            "JOIN documents d ON d.id = ri.document_id",
            "CROSS JOIN q",
            "WHERE",
            " AND ".join(clauses),
            "AND ri.search_vector @@ q.query",
            "ORDER BY score DESC, ri.id ASC",
            "LIMIT %s",
        ]
    )
    exec_params = [query.query_text, *params, query.top_k]
    rows = conn.execute(sql, tuple(exec_params)).fetchall()
    candidates: list[LaneCandidate] = []
    for rank, row in enumerate(rows, start=1):
        score = float(row[-1])
        candidates.append(
            _row_to_candidate(row[:-1], lane=lane, lane_rank=rank, score=_score_str(score))
        )
    return candidates


def lexical_lane(conn: DBConnection, query: LaneQuery) -> list[LaneCandidate]:
    """English FTS lane over all pinned, cutoff-safe items."""
    return _fts_lane(conn, query, lane=LANE_LEXICAL, kind=None)


def facts_lane(conn: DBConnection, query: LaneQuery) -> list[LaneCandidate]:
    """FTS lane over ``kind='fact'`` items; hits carry ``financial_fact_id``."""
    return _fts_lane(conn, query, lane=LANE_FACTS, kind="fact")


def tables_lane(conn: DBConnection, query: LaneQuery) -> list[LaneCandidate]:
    """FTS lane over ``kind='table_row'`` items; hits carry ``(table_id, row)``."""
    return _fts_lane(conn, query, lane=LANE_TABLES, kind="table_row")
