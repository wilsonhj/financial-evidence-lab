"""Failure boundaries around retrieval metering; no database required."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app import retrieval
from app.auth import TenantContext


def test_usage_insert_and_terminal_trace_share_one_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    @contextmanager
    def connection(ctx: TenantContext) -> Iterator[Any]:
        try:
            yield SimpleNamespace(execute=lambda *args: None)
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    def execute(*args: Any, **kwargs: Any) -> tuple[dict[str, int], Decimal]:
        events.append("terminal trace")
        kwargs["usage"].cost_usd = Decimal("0.1")
        return {}, Decimal("0.1")

    monkeypatch.setattr(retrieval, "tenant_connection", connection)
    monkeypatch.setattr(retrieval, "_execute_pipeline", execute)
    monkeypatch.setattr(retrieval, "record_usage", lambda *args: events.append("usage"))
    retrieval._run_pipeline_or_fail(
        TenantContext("org", "user", "owner"),
        run_id="run",
        plan={},
        mode="execute",
        embedding_provider="mock",
        embedding_model="mock",
        usage_kind="research_query",
    )
    assert events == ["terminal trace", "usage", "commit"]


def test_post_generation_failure_preserves_reported_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    failures: list[dict[str, Any]] = []

    @contextmanager
    def connection(ctx: TenantContext) -> Iterator[Any]:
        try:
            yield SimpleNamespace(execute=lambda *args: None)
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    def execute(*args: Any, **kwargs: Any) -> None:
        kwargs["usage"].cost_usd = Decimal("0.125")
        raise RuntimeError("verification write failed after provider response")

    monkeypatch.setattr(retrieval, "tenant_connection", connection)
    monkeypatch.setattr(retrieval, "_execute_pipeline", execute)
    monkeypatch.setattr(retrieval, "_record_run_failure", lambda ctx, **kw: failures.append(kw))
    retrieval._run_pipeline_or_fail(
        TenantContext("org", "user", "owner"),
        run_id="run",
        plan={},
        mode="execute",
        embedding_provider="mock",
        embedding_model="mock",
        usage_kind="research_query_rerun",
    )
    assert events == ["rollback"]
    assert len(failures) == 1
    assert failures[0]["cost_usd"] == Decimal("0.125")
    assert failures[0]["usage_kind"] == "research_query_rerun"
