"""Dispatch-layer durability and tenancy for ``extraction_run`` (defects D/F/G).

These are consumer-level tests: they enqueue a real job and drive
``run_worker`` against Postgres, because the defects they cover live in the
gap between the queue row and the handler's store selection — invisible to
any test that calls ``handle_extraction_run`` directly.

Runs against the isolated ``<db>_extraction`` sibling created by
``test_postgres_crash_resume.ensure_extraction_database``, for the reason
documented there: 0004 makes ``extraction_runs`` rows permanent, so committing
them to the shared TEST_DATABASE_URL would break every later suite's
``DELETE FROM corpus_versions`` cleanup.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers import queue
from fel_workers.consumer import run_worker
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.types import ExtractionRunRequest
from fel_workers.ingestion.discovery import JOB_KIND_SEC_DISCOVERY

from .conftest import FIXTURE_DOC, FIXTURE_SPAN
from .test_postgres_crash_resume import (
    _ORG,
    LONG_SPAN_TEXT,
    _request,
    _seed_parents,
    _seed_run,
    ensure_extraction_database,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"
)


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


def _payload(request: ExtractionRunRequest, *, evidence_key: str = "evidence") -> dict[str, Any]:
    """A production-shaped payload carrying inline evidence.

    ``evidence_key`` selects between the two spellings the runbook documents as
    interchangeable (``evidence`` / ``spans``) — defect F is that they were not.
    """
    return {
        "run_id": request.run_id,
        "org_id": request.org_id,
        "workspace_id": request.workspace_id,
        "entity_id": request.entity_id,
        "modes": list(request.modes),
        "as_of": request.as_of.isoformat(),
        "corpus_version_id": request.corpus_version_id,
        "ontology_version": request.ontology_version,
        "workflow_version": request.workflow_version,
        "provider": request.provider,
        "model": request.model,
        "policy_id": request.policy_id,
        "input_manifest": dict(request.input_manifest),
        "input_hash": request.input_hash,
        "issuer_label": request.issuer_label,
        evidence_key: [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "text": LONG_SPAN_TEXT,
                "text_hash": sha256_hex(LONG_SPAN_TEXT),
                "published_at": "2026-06-30T00:00:00+00:00",
            }
        ],
    }


def _seeded_run(
    conn: psycopg.Connection, *, queue_name: str = "extraction"
) -> ExtractionRunRequest:
    """Seed the tenant chain plus one queued ``extraction_runs`` row.

    Also drains ``queue_name``: `extraction_runs` rows are permanent under 0004,
    so this suite cannot reset the database between tests, and a job left queued
    by an earlier test (or an earlier run) would be claimed ahead of this one.
    """
    conn.execute("DELETE FROM jobs WHERE queue = %s", (queue_name,))
    request = _request(str(uuid.uuid4()))
    _seed_parents(conn)
    _seed_run(conn, request)
    return request


def _drive(conn: psycopg.Connection, *, queue_name: str = "extraction") -> int:
    return run_worker(
        conn,
        MockStorageProvider(),
        MockSecClient(),
        queue_name=queue_name,
        max_iterations=3,
        structured_llm=MockStructuredLLMProvider(),
    )


def _durable_counts(conn: psycopg.Connection, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
          (SELECT status FROM extraction_runs WHERE id = %(run)s),
          (SELECT count(*) FROM extraction_proposals WHERE run_id = %(run)s),
          (SELECT count(*) FROM extraction_run_steps WHERE run_id = %(run)s),
          (SELECT count(*) FROM extraction_run_events WHERE run_id = %(run)s)
        """,
        {"run": run_id},
    ).fetchone()
    assert row is not None
    return {
        "run_status": row[0],
        "proposals": row[1],
        "steps": row[2],
        "events": row[3],
    }


@requires_db
@pytest.mark.parametrize("evidence_key", ["evidence", "spans"])
def test_inline_evidence_payload_persists_durably(
    extraction_db_url: str, evidence_key: str
) -> None:
    """A payload with inline evidence must still write its output to Postgres.

    Defect D: the consumer selected in-memory stores from PAYLOAD SHAPE
    (``bool(job.payload.get("evidence"))``), so with a live connection the run
    produced proposals, returned ``waiting_review``, and ``queue.complete``
    flipped ``jobs.status`` to ``succeeded`` — while ``extraction_runs``,
    ``extraction_proposals``, ``extraction_run_steps`` and
    ``extraction_run_events`` were never touched. No warning, no telemetry: the
    only trace of the loss was absent rows.

    Defect F: the same selection tested ``evidence`` only, while the handler
    read ``evidence or spans``, so the two spellings the runbook documents as
    interchangeable failed OPPOSITELY — ``spans`` took the Postgres branch and
    ``evidence`` silently discarded everything. Both spellings are asserted
    here and must behave identically.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        request = _seeded_run(conn)
        queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=_payload(request, evidence_key=evidence_key),
            queue="extraction",
            org_id=_ORG,
        )
        assert _drive(conn) == 1
        durable = _durable_counts(conn, request.run_id)

    assert durable["run_status"] == "waiting_review", (
        "the run row never left 'queued': the workflow ran against in-memory "
        "stores and its entire output was discarded while the job reported success"
    )
    assert durable["proposals"] > 0, "no proposals were persisted"
    assert durable["steps"] > 0, "no step checkpoints were persisted"
    assert durable["events"] > 0, "no run events were persisted"


@requires_db
def test_null_job_org_is_refused_on_the_durable_path(extraction_db_url: str) -> None:
    """A job with no tenant binding must not persist on the payload's say-so.

    Defect G: ``handle_extraction_run`` compared payload and job org only when
    ``job.org_id`` was not None, so a NULL one was read as "no constraint" and
    the payload self-asserted its tenant. ``jobs.org_id`` is nullable by design
    and ``queue.enqueue`` defaults it to None, so this is the DEFAULT enqueue.

    The remaining control does not close it: this payload's org and workspace
    are genuinely consistent (both seeded), so ``assert_workspace_ownership``
    passes — it only checks that the pair agrees with itself, never that the
    enqueuer was entitled to that org. The bind has to come from the job row.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        request = _seeded_run(conn)
        job_id = queue.enqueue(
            conn,
            kind=JOB_KIND_EXTRACTION_RUN,
            payload=_payload(request),
            queue="extraction",
            # org_id omitted: the nullable default every existing caller uses.
            # max_attempts=1 so the refusal is terminal on the first claim —
            # queue.fail otherwise requeues, which would leave the job 'queued'
            # and say nothing about whether it was refused or merely retried.
            max_attempts=1,
        )
        completed = _drive(conn)
        job = conn.execute("SELECT status, error FROM jobs WHERE id = %s", (job_id,)).fetchone()
        durable = _durable_counts(conn, request.run_id)

    assert completed == 0, "an untenanted extraction_run was completed as successful"
    assert job is not None
    assert job[0] == "failed", job
    assert "org_id" in str(job[1]), job[1]
    assert durable["run_status"] == "queued", "the run was persisted without a tenant bind"
    assert durable["proposals"] == 0, "proposals were persisted without a tenant bind"


@requires_db
def test_null_org_platform_jobs_of_other_kinds_still_dispatch(extraction_db_url: str) -> None:
    """The tenant bind is scoped to extraction_run, not to the queue.

    ``jobs.org_id`` is nullable specifically so platform jobs can run without a
    tenant, and ``sec_discovery`` relies on it. Tightening extraction must not
    take those with it.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("DELETE FROM jobs WHERE queue = 'platform-null-org'")
        job_id = queue.enqueue(
            conn,
            kind=JOB_KIND_SEC_DISCOVERY,
            payload={"cik": "0000320193", "forms": ["8-K"], "limit": 1},
            queue="platform-null-org",
        )
        completed = _drive(conn, queue_name="platform-null-org")
        job = conn.execute("SELECT status, error FROM jobs WHERE id = %s", (job_id,)).fetchone()

    assert job is not None, "the platform job vanished"
    assert job[0] == "succeeded", job
    assert completed == 1
