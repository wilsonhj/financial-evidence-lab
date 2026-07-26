"""Mock end-to-end extraction workflow acceptance (M3-107)."""

from __future__ import annotations

from typing import Any

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.events import redact_payload
from fel_workers.extraction.handler import handle_extraction_run
from fel_workers.extraction.telemetry import emit


def test_mock_e2e_workflow_waiting_review(
    sample_run_payload: dict[str, Any], structured_llm: MockStructuredLLMProvider
) -> None:
    state = handle_extraction_run(
        None,
        structured_llm,
        sample_run_payload,
        use_memory_stores=True,
    )
    assert state.error is None, state.error
    assert state.status == "waiting_review"
    assert state.validated
    for draft in state.validated:
        assert draft.state == "needs_review"
        assert draft.kind == "kpi"


def test_mock_e2e_via_consumer_queue(
    sample_run_payload: dict[str, Any],
    structured_llm: MockStructuredLLMProvider,
) -> None:
    import os

    import psycopg
    import pytest

    from fel_providers.mocks import MockSecClient, MockStorageProvider
    from fel_workers import queue
    from fel_workers.consumer import run_worker
    from fel_workers.extraction.handler import DEFAULT_EXTRACTION_QUEUE, JOB_KIND_EXTRACTION_RUN

    if os.environ.get("TEST_DATABASE_URL") is None:
        pytest.skip("TEST_DATABASE_URL not configured")

    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM jobs WHERE queue = %s", (DEFAULT_EXTRACTION_QUEUE,))
        queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=sample_run_payload,
            queue=DEFAULT_EXTRACTION_QUEUE,
            idempotency_key=f"extraction-e2e|{sample_run_payload['run_id']}",
        )
        completed = run_worker(
            conn,
            MockStorageProvider(),
            MockSecClient(),
            queue_name=DEFAULT_EXTRACTION_QUEUE,
            max_iterations=3,
            structured_llm=structured_llm,
        )
        assert completed >= 1
        row = conn.execute(
            "SELECT status FROM jobs WHERE kind = %s ORDER BY created_at DESC LIMIT 1",
            (JOB_KIND_EXTRACTION_RUN,),
        ).fetchone()
        assert row is not None
        assert row[0] == "succeeded"


def test_telemetry_redacts_sensitive_keys(caplog: Any) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="fel_workers.extraction.telemetry"):
        emit(
            "step_started",
            run_id="00000000-0000-4000-8000-000000000001",
            step_name="classify",
            prompt="SECRET PROMPT TEXT",
            source_text="filing body",
        )
    assert "SECRET PROMPT TEXT" not in caplog.text
    assert "filing body" not in caplog.text
    cleaned = redact_payload({"prompt": "x", "run_id": "abc", "tokens": 3})
    assert cleaned["prompt"] == "[redacted]"
    assert cleaned["run_id"] == "abc"
