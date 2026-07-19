"""End-to-end build/publish against pgvector Postgres (M2-011 / T0202).

Covers row reuse, new-id-on-config-change, single-active after two publishes,
FK/CHECK-satisfying embeddings, and HNSW-vs-exact recall. Skips cleanly when
TEST_DATABASE_URL is unset (see conftest).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fel_providers import MockEmbeddingProvider
from fel_retrieval import (
    build_and_publish,
    build_index,
    build_items,
    embed_drafts,
    exact_knn,
    hnsw_search,
    make_index_version_spec,
    recall_at_k,
)

PROVIDER = "mock"
MODEL = "mock-embed-v1"

SeedFactory = Callable[[], Any]


def _spec(corpus_version_id: str, **overrides: Any):  # type: ignore[no-untyped-def]
    return make_index_version_spec(
        corpus_version_id=corpus_version_id,
        embedding_provider=PROVIDER,
        embedding_model=MODEL,
        **overrides,
    )


def _row(conn: Any, index_version_id: str) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, is_active, published_at FROM retrieval_index_versions WHERE id = %s",
        (index_version_id,),
    ).fetchone()
    assert row is not None
    return row


def test_build_and_publish_end_to_end(pg_conn: Any, seed_corpus: SeedFactory) -> None:
    seeded = seed_corpus()
    spec = _spec(seeded.corpus_version_id)
    outcome = build_and_publish(
        pg_conn, spec=spec, corpus=seeded.corpus, provider=MockEmbeddingProvider(512)
    )
    assert outcome.status == "ready"
    assert outcome.item_count > 0
    # Every staged item has a matching embedding (FK/CHECK satisfied on insert).
    assert outcome.embedding_count == outcome.item_count

    status, is_active, published_at = _row(pg_conn, spec.id)
    assert status == "ready"
    assert is_active is True
    assert published_at is not None


def test_rebuild_reuses_row(pg_conn: Any, seed_corpus: SeedFactory) -> None:
    seeded = seed_corpus()
    spec = _spec(seeded.corpus_version_id)
    first = build_and_publish(
        pg_conn, spec=spec, corpus=seeded.corpus, provider=MockEmbeddingProvider(512)
    )
    second = build_index(
        pg_conn, spec=spec, corpus=seeded.corpus, provider=MockEmbeddingProvider(512)
    )
    assert second.reused is True
    assert second.status == "ready"
    assert second.item_count == first.item_count
    assert second.embedding_count == first.embedding_count


def test_config_change_mints_new_id(pg_conn: Any, seed_corpus: SeedFactory) -> None:
    seeded = seed_corpus()
    base = _spec(seeded.corpus_version_id)
    changed = _spec(seeded.corpus_version_id, chunker_config={"kinds": ["passage"]})
    assert base.id != changed.id
    build_and_publish(pg_conn, spec=base, corpus=seeded.corpus, provider=MockEmbeddingProvider(512))
    build_index(pg_conn, spec=changed, corpus=seeded.corpus, provider=MockEmbeddingProvider(512))
    ids = {
        str(r[0])
        for r in pg_conn.execute(
            "SELECT id FROM retrieval_index_versions WHERE id IN (%s, %s)",
            (base.id, changed.id),
        ).fetchall()
    }
    assert ids == {base.id, changed.id}


def test_two_publishes_leave_single_active(pg_conn: Any, seed_corpus: SeedFactory) -> None:
    first_corpus = seed_corpus()
    first = _spec(first_corpus.corpus_version_id)
    build_and_publish(
        pg_conn, spec=first, corpus=first_corpus.corpus, provider=MockEmbeddingProvider(512)
    )
    second_corpus = seed_corpus()
    second = _spec(second_corpus.corpus_version_id)
    build_and_publish(
        pg_conn, spec=second, corpus=second_corpus.corpus, provider=MockEmbeddingProvider(512)
    )

    active = [
        str(r[0])
        for r in pg_conn.execute(
            "SELECT id FROM retrieval_index_versions WHERE is_active"
        ).fetchall()
    ]
    assert active == [second.id]
    assert _row(pg_conn, first.id)[0] == "superseded"
    assert _row(pg_conn, first.id)[1] is False


def test_hnsw_matches_exact_oracle(pg_conn: Any, seed_corpus: SeedFactory) -> None:
    seeded = seed_corpus()
    spec = _spec(seeded.corpus_version_id)
    build_and_publish(pg_conn, spec=spec, corpus=seeded.corpus, provider=MockEmbeddingProvider(512))

    # Recompute the staged vectors deterministically for the exact oracle.
    result = build_items(
        seeded.corpus, index_version_id=spec.id, chunker_config=spec.chunker_config
    )
    staged = [
        (draft.id, vector)
        for draft, vector in embed_drafts(MockEmbeddingProvider(512), result.items)
    ]
    assert len(staged) >= 4

    provider = MockEmbeddingProvider(512)
    query_vector = provider.embed(["operating income for fiscal 2025"])[0]

    k = 3
    exact = exact_knn(query_vector, staged, k)
    approx = hnsw_search(pg_conn, index_version_id=spec.id, query_vector=query_vector, k=k)
    assert len(approx) == k
    assert recall_at_k(exact, approx, k) >= 0.9
