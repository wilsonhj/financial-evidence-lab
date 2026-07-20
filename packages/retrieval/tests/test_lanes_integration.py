"""End-to-end lane retrieval against pgvector Postgres (M2-012 / T0203).

Seeds two documents straddling an ``as_of`` cutoff into one corpus, builds two
index versions over it, and asserts every lane returns only pinned + cutoff-safe
items, maps fact/table provenance, flips visibility when the cutoff moves, and
never surfaces cross-index rows. Skips cleanly when TEST_DATABASE_URL is unset.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fel_providers import MockEmbeddingProvider
from fel_retrieval import (
    LaneQuery,
    build_index,
    dense_lane,
    facts_lane,
    lexical_lane,
    make_index_version_spec,
    publish_index_version,
    tables_lane,
)

PROVIDER = "mock"
MODEL = "mock-embed-v1"

EARLY_PUBLISHED = datetime(2025, 1, 15, tzinfo=UTC)
LATE_PUBLISHED = datetime(2025, 12, 1, tzinfo=UTC)
CUTOFF = datetime(2025, 6, 30, tzinfo=UTC)
WIDE_CUTOFF = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class TwoDocIndex:
    index_version_id: str
    other_index_version_id: str
    early: Any
    late: Any


def _build_index_over(conn: Any, spec: Any, docs: list[Any]) -> None:
    """Stage every doc's items into one building index, then publish it."""
    for doc in docs:
        build_index(conn, spec=spec, corpus=doc.corpus, provider=MockEmbeddingProvider(512))
    publish_index_version(conn, spec.id, activate=False)


def _fixture(conn: Any, seed: Any) -> TwoDocIndex:
    corpus_version_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'draft')",
        (corpus_version_id, f"corpus-{corpus_version_id[:8]}"),
    )
    early = seed(corpus_version_id=corpus_version_id, published_at=EARLY_PUBLISHED)
    late = seed(corpus_version_id=corpus_version_id, published_at=LATE_PUBLISHED)

    spec_a = make_index_version_spec(
        corpus_version_id=corpus_version_id, embedding_provider=PROVIDER, embedding_model=MODEL
    )
    _build_index_over(conn, spec_a, [early, late])
    # Second index over the same corpus (distinct config -> distinct id/items).
    spec_b = make_index_version_spec(
        corpus_version_id=corpus_version_id,
        embedding_provider=PROVIDER,
        embedding_model=MODEL,
        chunker_config={"kinds": ["passage", "fact", "table_row"], "variant": "b"},
    )
    _build_index_over(conn, spec_b, [early, late])
    assert spec_a.id != spec_b.id
    return TwoDocIndex(spec_a.id, spec_b.id, early, late)


def _item_index(conn: Any, item_id: str) -> str:
    row = conn.execute(
        "SELECT index_version_id FROM retrieval_items WHERE id = %s", (item_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def _query(fx: TwoDocIndex, *, as_of: datetime, **overrides: Any) -> LaneQuery:
    vector = MockEmbeddingProvider(512).embed(["revenue and operating income in fiscal 2025"])[0]
    params: dict[str, Any] = {
        "index_version_id": fx.index_version_id,
        "as_of": as_of,
        "query_text": "revenue or sales or income or fiscal",
        "query_vector": vector,
    }
    params.update(overrides)
    return LaneQuery(**params)


def test_dense_lane_pin_and_cutoff(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    candidates = dense_lane(pg_conn, _query(fx, as_of=CUTOFF))
    assert candidates, "dense lane returned nothing at the cutoff"
    for cand in candidates:
        # Cutoff: only the early document is visible.
        assert cand.document_version_id == fx.early.document_version_id
        assert cand.published_at <= CUTOFF
        # Pin: every item belongs to the pinned index, never the sibling.
        assert _item_index(pg_conn, cand.item_id) == fx.index_version_id
    ranks = [c.lane_rank for c in candidates]
    assert ranks == sorted(ranks) and ranks[0] == 1


def test_lexical_lane_pin_and_cutoff(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    candidates = lexical_lane(pg_conn, _query(fx, as_of=CUTOFF))
    assert candidates
    late_dv = fx.late.document_version_id
    for cand in candidates:
        assert cand.document_version_id != late_dv
        assert _item_index(pg_conn, cand.item_id) == fx.index_version_id


def test_facts_lane_maps_financial_fact(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    candidates = facts_lane(pg_conn, _query(fx, as_of=CUTOFF))
    assert candidates
    for cand in candidates:
        assert cand.kind == "fact"
        assert cand.financial_fact_id is not None
        assert cand.table_id is None
        assert cand.document_version_id == fx.early.document_version_id
    assert fx.early.fact_id in {c.financial_fact_id for c in candidates}


def test_tables_lane_maps_table_row(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    candidates = tables_lane(pg_conn, _query(fx, as_of=CUTOFF))
    assert candidates
    for cand in candidates:
        assert cand.kind == "table_row"
        assert cand.table_id is not None
        assert cand.table_row_index is not None
        assert cand.financial_fact_id is None
    assert fx.early.table_id in {c.table_id for c in candidates}


def test_cutoff_widening_flips_visibility(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    narrow = lexical_lane(pg_conn, _query(fx, as_of=CUTOFF))
    wide = lexical_lane(pg_conn, _query(fx, as_of=WIDE_CUTOFF))
    narrow_dvs = {c.document_version_id for c in narrow}
    wide_dvs = {c.document_version_id for c in wide}
    # Narrow cutoff hides the late document; widening reveals it.
    assert fx.late.document_version_id not in narrow_dvs
    assert fx.late.document_version_id in wide_dvs
    assert fx.early.document_version_id in wide_dvs


def test_cross_index_items_never_appear(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    other_ids = {
        str(r[0])
        for r in pg_conn.execute(
            "SELECT id FROM retrieval_items WHERE index_version_id = %s",
            (fx.other_index_version_id,),
        ).fetchall()
    }
    assert other_ids  # sanity: the sibling index actually has items
    for lane in (dense_lane, lexical_lane, facts_lane, tables_lane):
        returned = {c.item_id for c in lane(pg_conn, _query(fx, as_of=WIDE_CUTOFF))}
        assert returned.isdisjoint(other_ids)


def test_entity_filter_pushed_down(pg_conn: Any, seed_document: Any) -> None:
    fx = _fixture(pg_conn, seed_document)
    hits = lexical_lane(
        pg_conn, _query(fx, as_of=WIDE_CUTOFF, entity_id=fx.early.corpus["entity_id"])
    )
    assert hits
    for cand in hits:
        assert cand.document_version_id == fx.early.document_version_id
