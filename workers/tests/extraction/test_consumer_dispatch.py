"""Consumer dispatches extraction_run (M3-102)."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers import queue
from fel_workers.consumer import run_worker
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN

from ..conftest import ensure_organization
from .conftest import sample_payload

requires_db = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)


class _FakeConn:
    """Minimal stand-in so dispatch tests can run without Postgres."""

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("DB not available in unit path")


def test_consumer_fails_extraction_without_structured_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown-capability path: missing structured_llm fails the job."""
    failed: list[str] = []

    monkeypatch.setattr(queue, "reap_stale", lambda *a, **k: 0)

    claimed = queue.ClaimedJob(
        id="job-1",
        kind=JOB_KIND_EXTRACTION_RUN,
        payload=sample_payload(),
        queue="ingestion",
        attempts=1,
        max_attempts=5,
        lease="lease",
    )

    def claim_one(conn: Any, queue: str = "ingestion") -> queue.ClaimedJob | None:
        del conn, queue
        nonlocal claimed
        job, claimed = claimed, None  # type: ignore[assignment]
        return job

    monkeypatch.setattr(queue, "claim_one", claim_one)
    monkeypatch.setattr(
        queue,
        "fail",
        lambda conn, job, err: failed.append(err),
    )
    monkeypatch.setattr(queue, "complete", lambda *a, **k: True)

    completed = run_worker(
        MagicMock(),  # type: ignore[arg-type]
        MockStorageProvider(),
        MockSecClient(),
        max_iterations=1,
        structured_llm=None,
    )
    assert completed == 0
    assert failed
    assert "StructuredLLMProvider" in failed[0]


@requires_db
def test_consumer_dispatches_extraction_run(corpus_conn: Any) -> None:
    """Claim-to-complete wiring for extraction_run through the real queue.

    Runs against the shared corpus database, so it cannot persist durably:
    `extraction_runs` rows are permanent under 0004 and would block every
    later suite's `DELETE FROM corpus_versions`. Memory stores are therefore
    requested explicitly — the durable path is covered in
    `test_dispatch_durability.py` against the isolated extraction sibling.
    """
    payload = sample_payload(modes=["kpi"])
    # jobs.org_id is a real foreign key since 0009; the tenant must exist.
    ensure_organization(payload["org_id"], name="dispatch org")
    queue.enqueue(
        corpus_conn,
        kind=JOB_KIND_EXTRACTION_RUN,
        payload=payload,
        queue="ingestion",
        idempotency_key=f"extraction|{payload['run_id']}",
        org_id=payload["org_id"],
    )
    completed = run_worker(
        corpus_conn,
        MockStorageProvider(),
        MockSecClient(),
        queue_name="ingestion",
        max_iterations=3,
        structured_llm=MockStructuredLLMProvider(),
        extraction_memory_stores=True,
    )
    assert completed == 1
    row = corpus_conn.execute(
        "SELECT status, error FROM jobs WHERE kind = %s",
        (JOB_KIND_EXTRACTION_RUN,),
    ).fetchone()
    assert row is not None
    assert row[0] == "succeeded"
