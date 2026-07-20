"""DB-less coverage of the build/publish control flow via a recording fake
connection. The atomic behaviour itself is exercised end-to-end against
Postgres in test_index_build_integration.py."""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from fel_providers import MockEmbeddingProvider
from fel_retrieval import (
    IndexBuildError,
    build_index,
    content_sha256,
    make_index_version_spec,
    publish_index_version,
)


def tiny_corpus() -> dict[str, Any]:
    canonical = "Revenue was $100 million in fiscal 2025."
    return {
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "document_id": "22222222-2222-4222-8222-222222222222",
        "document_version_id": "33333333-3333-4333-8333-333333333333",
        "form": "10-K",
        "canonical_text": canonical,
        "source_spans": [
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "section_id": "55555555-5555-4555-8555-555555555555",
                "start_char": 0,
                "end_char": len(canonical),
                "text": canonical,
                "text_hash": content_sha256(canonical),
                "heading_path": ["ITEM 8"],
            }
        ],
    }


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None, rowcount: int) -> None:
        self._row = row
        self.rowcount = rowcount

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [self._row] if self._row is not None else []


class FakeConn:
    """Records executed statements; answers status/count SELECTs from a script."""

    def __init__(self, status: str, *, publish_rowcount: int = 1) -> None:
        self._status = status
        self._publish_rowcount = publish_rowcount
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> FakeCursor:
        self.calls.append((query, params))
        stripped = " ".join(query.split())
        if stripped.startswith("SELECT status"):
            return FakeCursor((self._status,), 1)
        if stripped.startswith("SELECT count"):
            return FakeCursor((0,), 1)
        if "SET status = 'ready'" in stripped:
            return FakeCursor(None, self._publish_rowcount)
        return FakeCursor(None, 1)

    def transaction(self) -> contextlib.AbstractContextManager[Any]:
        return contextlib.nullcontext()

    def updates(self) -> list[tuple[str, Any]]:
        return [(" ".join(q.split()), p) for q, p in self.calls if q.split()[0].upper() == "UPDATE"]


def _spec():  # type: ignore[no-untyped-def]
    return make_index_version_spec(
        corpus_version_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        embedding_provider="mock",
        embedding_model="mock-embed-v1",
    )


def test_build_from_draft_transitions_to_building() -> None:
    conn = FakeConn("draft")
    outcome = build_index(
        conn, spec=_spec(), corpus=tiny_corpus(), provider=MockEmbeddingProvider(512)
    )
    assert outcome.status == "building"
    assert outcome.reused is False
    updates = conn.updates()
    assert any("SET status = 'building'" in u for u, _ in updates)
    inserts = [q for q, _ in conn.calls if q.strip().startswith("INSERT")]
    # one version insert + one passage item + one embedding
    assert sum("retrieval_index_versions" in q for q in inserts) == 1
    assert sum("retrieval_items" in q for q in inserts) == 1
    assert sum("retrieval_embeddings" in q for q in inserts) == 1


def test_build_reuses_ready_version_without_reinserting() -> None:
    conn = FakeConn("ready")
    outcome = build_index(
        conn, spec=_spec(), corpus=tiny_corpus(), provider=MockEmbeddingProvider(512)
    )
    assert outcome.status == "ready"
    assert outcome.reused is True
    assert not any(q.strip().startswith("INSERT INTO retrieval_items") for q, _ in conn.calls)


def test_build_rejects_failed_terminal_version() -> None:
    conn = FakeConn("failed")
    with pytest.raises(IndexBuildError, match="failed and immutable"):
        build_index(conn, spec=_spec(), corpus=tiny_corpus(), provider=MockEmbeddingProvider(512))


def test_publish_supersedes_active_before_activating_new() -> None:
    conn = FakeConn("building")
    publish_index_version(conn, "idx-1", activate=True)
    updates = conn.updates()
    assert len(updates) == 2
    # Supersede-old must run before ready+activate-new (single-active invariant).
    assert "is_active = false, status = 'superseded'" in updates[0][0]
    ready_sql, ready_params = updates[1]
    assert "SET status = 'ready'" in ready_sql
    assert ready_params == (True, "idx-1")


def test_publish_without_activation_skips_supersede() -> None:
    conn = FakeConn("building")
    publish_index_version(conn, "idx-1", activate=False)
    updates = conn.updates()
    assert len(updates) == 1
    ready_sql, ready_params = updates[0]
    assert "SET status = 'ready'" in ready_sql
    assert ready_params == (False, "idx-1")


def test_publish_raises_when_not_building() -> None:
    conn = FakeConn("building", publish_rowcount=0)
    with pytest.raises(IndexBuildError, match="not in 'building'"):
        publish_index_version(conn, "idx-1", activate=True)
