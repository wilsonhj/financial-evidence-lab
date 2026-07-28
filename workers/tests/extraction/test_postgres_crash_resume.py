"""Crash-resume against the REAL Postgres stores (#60 review residual).

Every other extraction test drives `MemoryCheckpointStore` / `MemoryEventStore`
/ `MemoryPersistStore`. Even the DB-gated e2e does: `sample_run_payload`
carries inline evidence, and `consumer.py` passes
`use_memory_stores=bool(job.payload.get("evidence"))`, so its Postgres
connection serves the job queue only and the workflow never touches
`PostgresCheckpointStore`.

That gap is why three separate defects in this package hid in the same place:
stage output not being restored after process death, span text being truncated
to 64 chars inside the event payload that carries it, and usage flushes racing
the terminal-run trigger. All three are invisible to an in-process run, because
`PostgresCheckpointStore._memory` answers from cache before the row is ever
read back.

This suite therefore resumes through a FRESH store object on a FRESH
connection, which is the only configuration that actually reads the durable
row. Skips without TEST_DATABASE_URL, as the other DB-backed suites do.

Runs against an isolated `<db>_extraction` sibling, for the same reason the
retrieval integration suites use `<db>_retrieval` (PR #119). These are the
first tests to commit durable `extraction_runs` rows, and 0004 makes them
permanent (`extraction_runs cannot be deleted`, `extraction_proposal_evidence
is append-only`), so they cannot be torn down. Each row pins the
`corpus_versions` row it references, while the shared `corpus_conn` fixture
deletes `corpus_versions` globally rather than per-org — so sharing the base
database would break every later suite in the same CI run at fixture setup,
not this one. See `ensure_extraction_database`.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import (
    PostgresCheckpointStore,
    PostgresEventStore,
    PostgresPersistStore,
)
from fel_workers.extraction.types import EvidenceBlock, ExtractionRunRequest, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import FIXTURE_DOC, FIXTURE_SPAN

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Deliberately over the 256-char redaction threshold: real filing spans are,
# and a shorter fixture is exactly what let the truncation defect survive.
LONG_SPAN_TEXT = "ARR was $100 million as of June 30, 2026. " * 16

_ORG = "00000000-0000-0000-0000-00000000c101"
_USER = "00000000-0000-0000-0000-00000000c201"
_WORKSPACE = "00000000-0000-0000-0000-00000000c301"
_ENTITY = "00000000-0000-0000-0000-00000000c401"
_CORPUS = "00000000-0000-0000-0000-00000000cb01"
_POLICY = "00000000-0000-0000-0000-00000000c501"
_DOCUMENT = "00000000-0000-0000-0000-00000000c601"
_SECTION = "00000000-0000-0000-0000-00000000c801"
# The mock provider cites these fixed ids in every proposal it emits, so the
# span chain must be seeded under them or the composite fk rejects the insert.
_SPAN = FIXTURE_SPAN
_DOC_VERSION = FIXTURE_DOC


def ensure_extraction_database(base_url: str) -> str:
    """Create and migrate a dedicated ``<db>_extraction`` sibling; return its URL.

    Mirrors `packages/retrieval/tests/conftest.py::ensure_retrieval_database`,
    for the same reason. These tests commit durable `extraction_runs` rows, and
    0004 makes them permanent (`extraction_runs cannot be deleted`,
    `extraction_proposal_evidence is append-only`). Such a row holds an FK to
    `corpus_versions`, so running against the base TEST_DATABASE_URL
    permanently blocks the workers/ingestion suites' `DELETE FROM
    corpus_versions` cleanup — every later suite sharing the database fails at
    fixture setup. An isolated sibling keeps that blast radius local. Roles are
    cluster-level, so grants inside the migrations resolve there too.

    Idempotent: creation swallows DuplicateDatabase, and the non-idempotent
    migrations run only when the marker table is absent.
    """
    parsed = urlsplit(base_url)
    extraction_db = parsed.path.lstrip("/") + "_extraction"
    extraction_url = urlunsplit(parsed._replace(path="/" + extraction_db))

    with psycopg.connect(base_url, autocommit=True) as conn:
        try:
            conn.execute(f'CREATE DATABASE "{extraction_db}"')  # noqa: S608 — derived name
        except psycopg.errors.DuplicateDatabase:
            pass

    repo_root = Path(__file__).resolve().parents[3]
    with psycopg.connect(extraction_url, autocommit=True) as conn:
        marker = conn.execute("SELECT to_regclass('public.extraction_runs')").fetchone()
        if marker is None or marker[0] is None:
            for path in sorted(repo_root.glob("db/migrations/*.sql")):
                conn.execute(path.read_text())
    return extraction_url


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


def _seed_parents(conn: psycopg.Connection) -> None:
    """Idempotent parent chain for an extraction_runs row."""
    conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
    for sql, args in (
        ("INSERT INTO organizations (id, name) VALUES (%s, 'Crash Resume Org')", (_ORG,)),
        (
            "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (_ORG, _USER),
        ),
        (
            "INSERT INTO workspaces (id, org_id, name, entity_id, base_currency,"
            " fiscal_calendar, as_of) VALUES (%s, %s, 'WS', %s, 'USD', 'calendar', now())",
            (_WORKSPACE, _ORG, _ENTITY),
        ),
        (
            "INSERT INTO corpus_versions (id, label, status, is_active, published_at)"
            " VALUES (%s, 'Crash Resume Corpus', 'active', true, now())",
            (_CORPUS,),
        ),
        (
            "INSERT INTO extraction_policies (id, org_id, version, created_by)"
            " VALUES (%s, %s, 1, %s)",
            (_POLICY, _ORG, _USER),
        ),
        # The span chain is required: extraction_proposal_evidence carries a
        # COMPOSITE fk (source_span_id, document_version_id) -> source_spans, so
        # persisting proposals fails without a real span row behind the pair.
        (
            "INSERT INTO documents (id, entity_id, accession, source_url,"
            " content_hash, storage_key, published_at) VALUES"
            " (%s, %s, 'cr-1', 'https://example.test/cr-1', %s, 'cr-1', now())",
            (_DOCUMENT, _ENTITY, sha256_hex("crash-resume-doc")),
        ),
        (
            "INSERT INTO document_versions (id, document_id, parser_version,"
            " normalizer_version, canonical_text_key) VALUES (%s, %s, 'p1', 'n1', 'text/cr')",
            (_DOC_VERSION, _DOCUMENT),
        ),
        (
            "INSERT INTO sections (id, document_version_id, heading, heading_path,"
            " ord, start_char, end_char) VALUES (%s, %s, 'One', ARRAY['One'], 0, 0, %s)",
            (_SECTION, _DOC_VERSION, len(LONG_SPAN_TEXT)),
        ),
        (
            "INSERT INTO source_spans (id, document_version_id, section_id,"
            " start_char, end_char, text_hash) VALUES (%s, %s, %s, 0, %s, %s)",
            (_SPAN, _DOC_VERSION, _SECTION, len(LONG_SPAN_TEXT), sha256_hex(LONG_SPAN_TEXT)),
        ),
    ):
        conn.execute(f"{sql} ON CONFLICT DO NOTHING", args)


def _request(run_id: str) -> ExtractionRunRequest:
    return ExtractionRunRequest(
        run_id=run_id,
        org_id=_ORG,
        workspace_id=_WORKSPACE,
        entity_id=_ENTITY,
        modes=("kpi",),
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        corpus_version_id=_CORPUS,
        ontology_version="saas-metrics/v1",
        workflow_version="extraction-workflow/v1",
        provider="mock",
        model="mock-structured-v1",
        policy_id=_POLICY,
        input_manifest={"source_span_ids": [_SPAN]},
        input_hash=sha256_hex("crash-resume-manifest"),
        issuer_label="Example SaaS",
    )


def _seed_run(conn: psycopg.Connection, request: ExtractionRunRequest) -> None:
    """Insert the run row the Postgres stores write against.

    0004 forbids inserting a non-queued run, so status is promoted afterwards
    the way PostgresPersistStore.mark_running does.
    """
    conn.execute(
        """
        INSERT INTO extraction_runs (
            id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
            ontology_version, workflow_version, provider, model, policy_id,
            input_hash, idempotency_key, created_by, status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued')
        """,
        (
            request.run_id,
            request.org_id,
            request.workspace_id,
            request.entity_id,
            list(request.modes),
            request.as_of,
            request.corpus_version_id,
            request.ontology_version,
            request.workflow_version,
            request.provider,
            request.model,
            request.policy_id,
            request.input_hash,
            f"crash-resume|{request.run_id}",
            _USER,
        ),
    )


def _evidence() -> list[EvidenceBlock]:
    return [
        EvidenceBlock(
            source_span_id=_SPAN,
            document_version_id=_DOC_VERSION,
            text=LONG_SPAN_TEXT,
            text_hash=sha256_hex(LONG_SPAN_TEXT),
            published_at=datetime(2026, 6, 30, tzinfo=UTC),
        )
    ]


class _ProcessDeath(BaseException):
    """Models SIGKILL/OOM: derives from BaseException so no handler runs.

    `crash_after_stages` raises RuntimeError, which the workflow's catch-all
    now converts into a terminal `failed` run — correct for an untyped escape,
    but it is not what resume exists for. Resume targets the case where the
    process dies mid-run and the row is left `running`, so the injected death
    must bypass every handler the way a real signal does.
    """


class _CountingLLM:
    """Counts model calls so a resume that re-ran a stage is detectable.

    With `die_after` set, the process "dies" once that many calls have been
    served, after the stage's own commit has already landed in Postgres.
    """

    def __init__(self, *, die_after: int | None = None) -> None:
        self._inner = MockStructuredLLMProvider()
        self.provider = self._inner.provider
        self.model = self._inner.model
        self.calls = 0
        self._die_after = die_after

    def generate_structured(self, request: Any) -> Any:
        if self._die_after is not None and self.calls >= self._die_after:
            raise _ProcessDeath("simulated process death")
        self.calls += 1
        return self._inner.generate_structured(request)


def _postgres_deps(conn: psycopg.Connection, llm: _CountingLLM, **extra: Any) -> WorkflowDeps:
    """Real Postgres stores — never the memory doubles."""
    return WorkflowDeps(
        structured_llm=llm,
        checkpoint=PostgresCheckpointStore(conn=conn),
        events=PostgresEventStore(conn=conn),
        persist=PostgresPersistStore(conn),
        evidence_loader=lambda _r: _evidence(),
        **extra,
    )


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_crash_and_resume_through_real_postgres_stores(extraction_db_url: str) -> None:
    """Resume after process death must restore stage output from the durable row.

    The second pass uses new store objects on a new connection, so
    `PostgresCheckpointStore._memory` is empty and `load_succeeded` has to
    rehydrate from `extraction_run_events`. If it returns `output=None` the
    workflow re-runs committed stages, which the call counter catches.
    """

    # Baseline: an uninterrupted run, to know how much model work the pipeline
    # costs exactly once. Resume must not exceed it.
    baseline_request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, baseline_request)
        PostgresPersistStore(conn).mark_running(run_id=baseline_request.run_id, org_id=_ORG)
        baseline = _CountingLLM()
        clean = run_extraction_workflow(
            WorkflowState(request=baseline_request, evidence=_evidence()),
            _postgres_deps(conn, baseline),
        )
    assert clean.status == "waiting_review"
    assert baseline.calls >= 1

    run_id = str(uuid.uuid4())
    request = _request(run_id)
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        # Die after the first model stage commits, so resume has real work to
        # skip. BaseException => no handler runs, the row stays `running`.
        first = _CountingLLM(die_after=2)
        with pytest.raises(_ProcessDeath):
            run_extraction_workflow(
                WorkflowState(request=request, evidence=_evidence()),
                _postgres_deps(conn, first),
            )
        assert first.calls >= 1, "the crashed pass must have committed real model work"
        status = conn.execute(
            "SELECT status FROM extraction_runs WHERE id = %s", (run_id,)
        ).fetchone()
        assert (
            status is not None and status[0] == "running"
        ), "process death must leave the run resumable, not terminal"

    # Process death: nothing survives but the database.
    with psycopg.connect(extraction_db_url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        second = _CountingLLM()
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(fresh_conn, second),
        )

    assert final.status == "waiting_review"
    assert first.calls + second.calls <= baseline.calls, (
        "resume re-ran committed stages: durable stage output was not restored "
        f"(crashed={first.calls}, resumed={second.calls}, uninterrupted={baseline.calls})"
    )
    # Blocker 2 on the real path: the pinned span must survive the event round trip.
    assert [b.text for b in final.evidence] == [LONG_SPAN_TEXT]
    assert all(b.text_hash == sha256_hex(b.text) for b in final.evidence)


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_stage_output_round_trips_through_the_durable_event_row(extraction_db_url: str) -> None:
    """Narrow guard on the mechanism the resume above depends on.

    `extraction_run_steps` has no output column, so `load_succeeded` hydrates
    from the `step_completed` event payload. A fresh store proves the read
    comes from Postgres rather than the in-process cache.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        llm = _CountingLLM(die_after=2)
        with pytest.raises(_ProcessDeath):
            run_extraction_workflow(
                WorkflowState(request=request, evidence=_evidence()),
                _postgres_deps(conn, llm),
            )
        committed = conn.execute(
            """
            SELECT step_name, input_hash FROM extraction_run_steps
             WHERE org_id = %s AND run_id = %s AND status = 'succeeded'
             ORDER BY step_name LIMIT 1
            """,
            (_ORG, run_id),
        ).fetchone()
    assert committed is not None, "the crashed pass committed no succeeded step"
    step_name, input_hash = committed

    with psycopg.connect(extraction_db_url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        record = PostgresCheckpointStore(conn=fresh_conn).load_succeeded(
            run_id=run_id,
            org_id=_ORG,
            step_name=step_name,
            input_hash=input_hash,
            workflow_version=request.workflow_version,
        )

    assert record is not None
    assert record.status == "succeeded"
    assert record.output is not None, (
        "stage output was not restored from the durable event row: a resumed run "
        "would silently re-extract with the stage's result lost"
    )


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_terminal_event_is_written_before_the_run_row_goes_terminal(extraction_db_url: str) -> None:
    """A failing run must still persist its `run_failed` event.

    0004's `fel_assert_extraction_run_open` rejects every child insert once the
    run row is terminal, so a handler that writes the status before appending
    its terminal event loses the event AND masks the original exception with
    the guard's own error. Only the non-terminal `waiting_review` branch
    escaped this, which is exactly the branch the memory-backed happy path
    covers.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)

        # RuntimeError is an untyped escape: the catch-all lands the run row
        # `failed`, emits run_failed, and re-raises the ORIGINAL error.
        with pytest.raises(RuntimeError, match="injected crash"):
            run_extraction_workflow(
                WorkflowState(request=request, evidence=_evidence()),
                _postgres_deps(conn, _CountingLLM(), crash_after_stages=4),
            )

        status = conn.execute(
            "SELECT status FROM extraction_runs WHERE id = %s", (run_id,)
        ).fetchone()
        assert status is not None and status[0] == "failed"

        events = conn.execute(
            """
            SELECT count(*) FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'run_failed'
            """,
            (_ORG, run_id),
        ).fetchone()
    assert (
        events is not None and events[0] == 1
    ), "run_failed was not persisted: the terminal status write beat the event append"
