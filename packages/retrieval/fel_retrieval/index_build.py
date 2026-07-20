"""Versioned index build + atomic publish (M2-011 / T0202).

Runtime code here is driver-agnostic: it accepts an injected DB-API/psycopg
connection and never imports a driver, so ``fel_retrieval`` stays importable
with the standard library alone. All writes assume the caller connected as the
service/worker role (fel_app is SELECT-only on these shared tables).

Lifecycle honoured from ``db/migrations/0003_retrieval_core.sql``:
``draft -> building -> ready`` (published_at set, optionally is_active), with
``building -> failed`` on a build error.

Because the schema couples ``status='ready'`` with a non-null ``published_at``
and forbids activating an already-``ready`` row, activation happens *at* the
building->ready transition. Publish is therefore a single transaction that
supersedes the current active version and readies+activates the new one, so the
partial single-active unique index never sees two active rows.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from fel_retrieval.embeddings import EmbeddingProvider, embed_drafts, format_halfvec
from fel_retrieval.index_version import IndexVersionSpec
from fel_retrieval.item_builder import build_items
from fel_retrieval.models import BuildResult, RetrievalItemDraft


class _Cursor(Protocol):
    def fetchone(self) -> tuple[Any, ...] | None: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...


class DBConnection(Protocol):
    """Minimal surface of an injected psycopg/DB-API connection."""

    def execute(self, query: str, params: Any = None) -> _Cursor: ...
    def transaction(self) -> AbstractContextManager[Any]: ...


_TERMINAL_PUBLISHED = ("ready", "superseded")


class IndexBuildError(RuntimeError):
    """Raised when a build targets a terminal (failed) index version."""


@dataclass(frozen=True)
class BuildOutcome:
    index_version_id: str
    status: str
    reused: bool
    item_count: int
    embedding_count: int
    rejection_count: int
    build_result: BuildResult | None


_INSERT_VERSION = """
    INSERT INTO retrieval_index_versions (
        id, corpus_version_id, status, chunker_version, chunker_config,
        config_hash, embedding_provider, embedding_model, dimensions, distance
    ) VALUES (%s, %s, 'draft', %s, %s::jsonb, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO NOTHING
"""

_INSERT_ITEM = """
    INSERT INTO retrieval_items (
        id, index_version_id, kind, entity_id, document_id, document_version_id,
        section_id, source_span_id, financial_fact_id, table_id, table_row_index,
        content, content_sha256, heading_path, start_char, end_char, token_count,
        form, period, metadata
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s::jsonb
    )
    ON CONFLICT (index_version_id, kind, source_anchor, content_sha256)
        DO NOTHING
"""

_INSERT_EMBEDDING = """
    INSERT INTO retrieval_embeddings (
        retrieval_item_id, index_version_id, provider, model, dimensions,
        embedding, content_sha256
    ) VALUES (%s, %s, %s, %s, %s, %s::halfvec(512), %s)
    ON CONFLICT (retrieval_item_id, provider, model, dimensions) DO NOTHING
"""


def _current_status(conn: DBConnection, index_version_id: str) -> str | None:
    row = conn.execute(
        "SELECT status FROM retrieval_index_versions WHERE id = %s",
        (index_version_id,),
    ).fetchone()
    return None if row is None else str(row[0])


def _count_items(conn: DBConnection, index_version_id: str) -> int:
    row = conn.execute(
        "SELECT count(id) FROM retrieval_items WHERE index_version_id = %s",
        (index_version_id,),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _count_embeddings(conn: DBConnection, index_version_id: str) -> int:
    row = conn.execute(
        "SELECT count(retrieval_item_id) FROM retrieval_embeddings WHERE index_version_id = %s",
        (index_version_id,),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _item_params(draft: RetrievalItemDraft) -> tuple[Any, ...]:
    return (
        draft.id,
        draft.index_version_id,
        draft.kind,
        draft.entity_id,
        draft.document_id,
        draft.document_version_id,
        draft.section_id,
        draft.source_span_id,
        draft.financial_fact_id,
        draft.table_id,
        draft.table_row_index,
        draft.content,
        draft.content_sha256,
        list(draft.heading_path),
        draft.start_char,
        draft.end_char,
        draft.token_count,
        draft.form,
        draft.period,
        json.dumps(draft.metadata, sort_keys=True),
    )


def build_index(
    conn: DBConnection,
    *,
    spec: IndexVersionSpec,
    corpus: Mapping[str, Any],
    provider: EmbeddingProvider,
) -> BuildOutcome:
    """Insert (or resume) the version and stage items + embeddings.

    Identical pinned inputs reuse the same row: a version already ``ready`` or
    ``superseded`` returns untouched; a ``draft``/``building`` row is resumed
    idempotently. Leaves the version in ``building`` for a later publish.
    """
    conn.execute(
        _INSERT_VERSION,
        (
            spec.id,
            spec.corpus_version_id,
            spec.chunker_version,
            json.dumps(spec.chunker_config, sort_keys=True),
            spec.config_hash,
            spec.embedding_provider,
            spec.embedding_model,
            spec.dimensions,
            spec.distance,
        ),
    )
    status = _current_status(conn, spec.id)
    if status is None:  # pragma: no cover - insert-or-conflict guarantees a row
        raise IndexBuildError(f"index version {spec.id} vanished after insert")

    if status in _TERMINAL_PUBLISHED:
        return BuildOutcome(
            index_version_id=spec.id,
            status=status,
            reused=True,
            item_count=_count_items(conn, spec.id),
            embedding_count=_count_embeddings(conn, spec.id),
            rejection_count=0,
            build_result=None,
        )
    if status == "failed":
        raise IndexBuildError(
            f"index version {spec.id} is failed and immutable; change a pin to rebuild"
        )

    if status == "draft":
        conn.execute(
            "UPDATE retrieval_index_versions SET status = 'building' "
            "WHERE id = %s AND status = 'draft'",
            (spec.id,),
        )

    try:
        result = build_items(
            corpus,
            index_version_id=spec.id,
            chunker_config=spec.chunker_config,
        )
        for draft in result.items:
            conn.execute(_INSERT_ITEM, _item_params(draft))
        for draft, vector in embed_drafts(provider, result.items, dimensions=spec.dimensions):
            conn.execute(
                _INSERT_EMBEDDING,
                (
                    draft.id,
                    spec.id,
                    spec.embedding_provider,
                    spec.embedding_model,
                    spec.dimensions,
                    format_halfvec(vector),
                    draft.content_sha256,
                ),
            )
    except Exception:
        conn.execute(
            "UPDATE retrieval_index_versions SET status = 'failed' "
            "WHERE id = %s AND status = 'building'",
            (spec.id,),
        )
        raise

    return BuildOutcome(
        index_version_id=spec.id,
        status="building",
        reused=False,
        item_count=_count_items(conn, spec.id),
        embedding_count=_count_embeddings(conn, spec.id),
        rejection_count=len(result.rejections),
        build_result=result,
    )


def publish_index_version(
    conn: DBConnection,
    index_version_id: str,
    *,
    activate: bool = True,
) -> None:
    """Atomically ready (and optionally activate) a ``building`` version.

    When activating, the current active version is superseded first, inside the
    same transaction, so the single-active partial unique index is never
    violated. Any failure rolls the whole flip back — no partial activation.
    """
    with conn.transaction():
        if activate:
            conn.execute(
                "UPDATE retrieval_index_versions "
                "SET is_active = false, status = 'superseded' "
                "WHERE is_active = true AND id <> %s",
                (index_version_id,),
            )
        cur = conn.execute(
            "UPDATE retrieval_index_versions "
            "SET status = 'ready', published_at = now(), is_active = %s "
            "WHERE id = %s AND status = 'building'",
            (activate, index_version_id),
        )
        if getattr(cur, "rowcount", -1) == 0:
            raise IndexBuildError(
                f"index version {index_version_id} is not in 'building' status to publish"
            )


def hnsw_search(
    conn: DBConnection,
    *,
    index_version_id: str,
    query_vector: Any,
    k: int,
) -> list[str]:
    """Approximate top-k item ids via the cosine HNSW index (``<=>``)."""
    conn.execute("SET hnsw.ef_search = 100")
    rows = conn.execute(
        "SELECT retrieval_item_id FROM retrieval_embeddings "
        "WHERE index_version_id = %s "
        "ORDER BY embedding <=> %s::halfvec(512) LIMIT %s",
        (index_version_id, format_halfvec(query_vector), k),
    ).fetchall()
    return [str(row[0]) for row in rows]


def build_and_publish(
    conn: DBConnection,
    *,
    spec: IndexVersionSpec,
    corpus: Mapping[str, Any],
    provider: EmbeddingProvider,
    activate: bool = True,
) -> BuildOutcome:
    """Convenience: build then publish, unless the version was already ready."""
    outcome = build_index(conn, spec=spec, corpus=corpus, provider=provider)
    if outcome.status == "building":
        publish_index_version(conn, spec.id, activate=activate)
        return BuildOutcome(
            index_version_id=outcome.index_version_id,
            status="ready",
            reused=outcome.reused,
            item_count=outcome.item_count,
            embedding_count=outcome.embedding_count,
            rejection_count=outcome.rejection_count,
            build_result=outcome.build_result,
        )
    return outcome
