"""Crash-resume against the REAL Postgres stores (#60 review residual).

Every other extraction test drives `MemoryCheckpointStore` / `MemoryEventStore`
/ `MemoryPersistStore`. Even the DB-gated e2e does: `sample_run_payload`
carries inline evidence, and `consumer.py` passes
`use_memory_stores=bool(job.payload.get("evidence"))`, so its Postgres
connection serves the job queue only and the workflow never touches
`PostgresCheckpointStore`.

That gap is why three separate defects in this package hid in the same place:
stage output not being restored after process death, span text being truncated
to 64 chars inside the event payload that used to carry it (before ADR-0011 gave
it a column), and usage flushes racing the terminal-run trigger. All three are
invisible to an in-process run, because
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

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.events import ExtractionEvent
from fel_workers.extraction.hashing import hash_json, sha256_hex
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

    Idempotent, and — since ADR-0011 — idempotent in the way that actually
    matters. The old marker check was ``to_regclass('public.extraction_runs')``:
    present means "migrated", so a sibling database created before a NEW
    migration landed was never brought forward. Anyone with a pre-existing
    ``<db>_extraction`` would have run this suite against a schema with no
    ``extraction_run_steps.output`` column, and the whole crash-resume suite
    would have been testing a code path the database could not support — a green
    run proving nothing, which is worse than a red one.

    The check is therefore against the CURRENT schema, not against the first
    migration that ever created it. A database that is stale rather than absent
    is dropped and rebuilt: migrations are not individually idempotent, so
    replaying them over a partially-migrated database is not an option, and a
    test sibling is disposable by construction (that is why it exists).
    """
    parsed = urlsplit(base_url)
    extraction_db = parsed.path.lstrip("/") + "_extraction"
    extraction_url = urlunsplit(parsed._replace(path="/" + extraction_db))
    repo_root = Path(__file__).resolve().parents[3]

    if _schema_is_current(extraction_url):
        return extraction_url

    with psycopg.connect(base_url, autocommit=True) as conn:
        # DROP is safe: `_schema_is_current` already said this database is either
        # absent or behind the migrations, and nothing outside this suite owns it.
        conn.execute(f'DROP DATABASE IF EXISTS "{extraction_db}" WITH (FORCE)')  # noqa: S608
        conn.execute(f'CREATE DATABASE "{extraction_db}"')  # noqa: S608 — derived name

    with psycopg.connect(extraction_url, autocommit=True) as conn:
        for path in sorted(repo_root.glob("db/migrations/*.sql")):
            conn.execute(path.read_text())
    if not _schema_is_current(extraction_url):  # pragma: no cover — defensive
        raise RuntimeError(f"{extraction_db} is still behind db/migrations after applying them")
    return extraction_url


# One probe per schema fact this suite depends on. Add to it whenever a new
# migration lands something the extraction tests read or write, or the staleness
# check silently stops being a check.
_SCHEMA_PROBES: tuple[str, ...] = (
    # 0004
    "SELECT to_regclass('public.extraction_runs') IS NOT NULL",
    "SELECT to_regclass('public.extraction_run_steps') IS NOT NULL",
    # 0006 (ADR-0011): the durable stage-output column and its pair CHECK.
    """
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'extraction_run_steps'
           AND column_name = 'output'
    )
    """,
    """
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'extraction_run_steps_output_pair'
    )
    """,
    # 0006 (issue #194): unscored proposals persist NULL, not 0.
    """
    SELECT NOT attnotnull FROM pg_attribute
     WHERE attrelid = 'public.extraction_proposals'::regclass
       AND attname = 'record_confidence'
    """,
)


def _schema_is_current(extraction_url: str) -> bool:
    """True when the sibling database exists AND every probe passes."""
    try:
        with psycopg.connect(extraction_url, autocommit=True) as conn:
            for probe in _SCHEMA_PROBES:
                row = conn.execute(probe).fetchone()
                if row is None or row[0] is not True:
                    return False
    except psycopg.OperationalError:
        return False  # database does not exist yet
    return True


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

    ``input_manifest`` is seeded from the request like every other pin: it is on
    ``fel_guard_extraction_run``'s immutable list, and the durable path now binds
    the payload to the row, so a fixture that left the column at its ``'{}'``
    default while the payload declared a manifest would be modelling a
    contradicted run rather than a well-formed one.
    """
    conn.execute(
        """
        INSERT INTO extraction_runs (
            id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
            ontology_version, workflow_version, provider, model, policy_id,
            input_manifest, input_hash, idempotency_key, created_by, status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,'queued')
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
            json.dumps(dict(request.input_manifest)),
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
def test_stage_output_round_trips_through_the_durable_step_row(extraction_db_url: str) -> None:
    """Narrow guard on the mechanism the resume above depends on.

    `load_succeeded` reads `extraction_run_steps.output` (migration 0006). A
    fresh store proves the read comes from Postgres rather than the in-process
    cache, and the recomputed hash proves the column and `output_hash` describe
    the same bytes.
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
        "stage output was not restored from the durable step row: a resumed run "
        "would silently re-extract with the stage's result lost"
    )
    assert record.output_hash == hash_json(record.output), (
        "the durable output does not hash to its output_hash: the two are written "
        "in one INSERT precisely so they cannot disagree"
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


# ---------------------------------------------------------------------------
# PR #145 blocker 4 — the step commit and its output-carrying event were two
# separate transactions under `autocommit=True`.
# ---------------------------------------------------------------------------

# The stage whose output IS the run's product: lose `extract_kpi`'s output and
# there are no raw proposals, so normalize and validate produce nothing and the
# run "abstains" — indistinguishable, from the outside, from a filing that
# genuinely stated no KPI.
_TORN_STEP = "extract_kpi"


@dataclass
class _LosingEventStore(PostgresEventStore):
    """Silently drops the `step_completed` event for one step.

    This is the *observable* state a death between `commit_succeeded` and the
    event append leaves behind, and the only injection that reproduces it on both
    sides of the fix: a durably `succeeded` step row with `output_hash NOT NULL`
    and no event carrying its `stage_output`. Dropping the append (rather than
    raising) means the surrounding transaction still commits, so the step row is
    durable exactly as an autocommit-era crash left it. An event pruned or lost
    later leaves the same row, which is why the resume-side guard is needed even
    now that the pair is atomic.
    """

    lose_on_step: str = ""

    def append(self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> Any:
        if event_type == "step_completed" and payload.get("step_name") == self.lose_on_step:
            return ExtractionEvent(event_type=event_type, payload={})
        return super().append(org_id=org_id, run_id=run_id, event_type=event_type, payload=payload)


class _ExplodingEventStore(PostgresEventStore):
    """Fails the `step_completed` append for one step, inside the transaction."""

    fail_on_step: str = ""

    def append(self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> Any:
        if event_type == "step_completed" and payload.get("step_name") == self.fail_on_step:
            raise RuntimeError(f"injected event-append failure for {self.fail_on_step}")
        return super().append(org_id=org_id, run_id=run_id, event_type=event_type, payload=payload)


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_death_between_step_commit_and_its_event_does_not_silently_abstain(
    extraction_db_url: str,
) -> None:
    """A torn checkpoint must never be mistaken for a completed stage.

    The injected loss puts the database in exactly the state a death in the
    window between `commit_succeeded` and the `step_completed` append leaves: the
    `extract_kpi` step row is durably `succeeded` with a non-null `output_hash`,
    and the only carrier of its output is gone. On resume `load_succeeded` finds
    the row but `_load_stage_output` finds no event, so `output` is None while
    `output_hash` is not.

    Before the fix the workflow treated that as a completed stage:
    `stages.io.restore_output` returned early, `extract_kpi` was skipped with ZERO model
    calls, and the run landed `succeeded` + `abstained=True` with no proposals —
    silent data loss reported as a legitimate abstention, and permanent, because
    0004 forbids re-opening a terminal run. Verified at PR #145 head: the resumed
    run reported `status=succeeded abstained=True proposals=0 model_calls=0`.

    Since migration 0006 this scenario is no longer about resume at all — the
    output is on the step row and the resume succeeds from it (see
    `test_resume_succeeds_with_the_step_completed_event_never_written`). What is
    still asserted here is that the run does NOT abstain, whichever way it gets
    there, because that is the observable defect.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        events = _LosingEventStore(conn=conn, lose_on_step=_TORN_STEP)
        run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            WorkflowDeps(
                structured_llm=_CountingLLM(),
                checkpoint=PostgresCheckpointStore(conn=conn),
                events=events,
                persist=PostgresPersistStore(conn),
                evidence_loader=lambda _r: _evidence(),
            ),
        )

        # Precondition: the database really is in the torn state under test.
        step_row = conn.execute(
            """
            SELECT output_hash FROM extraction_run_steps
             WHERE org_id = %s AND run_id = %s AND step_name = %s AND status = 'succeeded'
            """,
            (_ORG, run_id, _TORN_STEP),
        ).fetchone()
        assert step_row is not None and step_row[0] is not None, (
            "the injected loss did not leave a durably succeeded step: "
            "this test is no longer exercising the window it targets"
        )
        lost = conn.execute(
            """
            SELECT count(*) FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'step_completed'
               AND payload->>'step_name' = %s
            """,
            (_ORG, run_id, _TORN_STEP),
        ).fetchone()
        assert lost is not None and lost[0] == 0, "the step_completed event survived"

    # Process death: nothing survives but the database. Resume on a fresh store
    # and connection, so the answer comes from Postgres, not an in-process cache.
    with psycopg.connect(extraction_db_url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        second = _CountingLLM()
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(fresh_conn, second),
        )

    assert not final.abstained, (
        "the resumed run abstained: a torn checkpoint was treated as a completed "
        "stage, so the extraction silently produced nothing and reported it as if "
        "the filing had stated nothing"
    )
    assert final.status == "waiting_review"
    assert final.validated, "the resumed run produced no proposals"


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_resume_succeeds_with_the_step_completed_event_never_written(
    extraction_db_url: str,
) -> None:
    """The load-bearing test for ADR-0011: the step ROW alone carries the output.

    The `step_completed` event for `extract_kpi` is dropped on append — not
    DELETEd, which 0004 forbids outright (`extraction_run_events` is append-only
    and `fel_app` holds only SELECT, INSERT on it). What survives is exactly what
    a death between the step commit and its event append leaves behind.

    Three assertions, and the third is the one the old design could not express:

    (a) zero `step_completed` rows for that step — the precondition;
    (b) `load_succeeded` returns a non-null output anyway, hydrated from
        `extraction_run_steps.output`, so `_run_stage` skips the stage;
    (c) ZERO model calls on the resumed pass. Under the event-carried checkpoint
        this had to be `>= 1` (the stage was re-run), which is a passing
        assertion for a design that lost the stage's result.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            WorkflowDeps(
                structured_llm=_CountingLLM(),
                checkpoint=PostgresCheckpointStore(conn=conn),
                events=_LosingEventStore(conn=conn, lose_on_step=_TORN_STEP),
                persist=PostgresPersistStore(conn),
                evidence_loader=lambda _r: _evidence(),
            ),
        )
        # (a) The event really is absent.
        lost = conn.execute(
            """
            SELECT count(*) FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'step_completed'
               AND payload->>'step_name' = %s
            """,
            (_ORG, run_id, _TORN_STEP),
        ).fetchone()
        assert lost is not None and lost[0] == 0, "the step_completed event survived"
        step = conn.execute(
            """
            SELECT input_hash, output_hash, output IS NOT NULL
              FROM extraction_run_steps
             WHERE org_id = %s AND run_id = %s AND step_name = %s AND status = 'succeeded'
            """,
            (_ORG, run_id, _TORN_STEP),
        ).fetchone()
        assert step is not None and step[1] is not None
        assert step[2] is True, "the step row carries no output: 0006 is not in effect"

    # Process death: nothing survives but the database.
    with psycopg.connect(extraction_db_url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        # (b) The output comes back off the row, with no event to read.
        record = PostgresCheckpointStore(conn=fresh_conn).load_succeeded(
            run_id=run_id,
            org_id=_ORG,
            step_name=_TORN_STEP,
            input_hash=step[0],
            workflow_version=request.workflow_version,
        )
        assert record is not None and record.output is not None
        assert record.output_hash == hash_json(record.output)

    with psycopg.connect(extraction_db_url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        second = _CountingLLM()
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(fresh_conn, second),
        )

    # (c) Nothing was re-extracted.
    assert second.calls == 0, (
        "the resumed run made model calls: a stage whose output was durable on "
        "its step row was re-executed, which is the cost ADR-0011 removes"
    )
    assert final.status == "waiting_review"
    assert not final.abstained
    assert final.validated


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_no_persisted_event_payload_carries_evidence_text(extraction_db_url: str) -> None:
    """`data-model.md:23`, machine-checked against a full durable run.

    "Payload contains IDs/counts/status, never evidence or prompt text." That
    sentence was false for as long as `step_completed` carried `stage_output`;
    it is now true, and prose is not the place to keep a guarantee that a query
    can settle.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(conn, _CountingLLM()),
        )
        rows = conn.execute(
            "SELECT event_type, payload::text FROM extraction_run_events"
            " WHERE org_id = %s AND run_id = %s",
            (_ORG, run_id),
        ).fetchall()

    assert rows, "the run persisted no events"
    # The pinned span text, and a distinctive fragment of it, must appear nowhere.
    for event_type, payload_text in rows:
        assert LONG_SPAN_TEXT not in payload_text, event_type
        assert "ARR was $100 million as of June 30, 2026." not in payload_text, event_type
        assert '"stage_output"' not in payload_text, event_type


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_tampered_durable_output_forces_re_execution(extraction_db_url: str) -> None:
    """Issue #158 against the real column: the hash is what makes the row trustworthy.

    `extraction_run_steps.output` is UPDATE-able within an open run — 0004's
    guard pins identity columns, and its own comment says steps may advance
    status/output — so the row is not a trusted memory space. A resumed run that
    took it on faith would recompute `raw_payload_hash` and `proposal_id_for`
    over the substituted payload and emit proposals describing something the
    extractor never produced.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        first = _CountingLLM(die_after=2)
        with pytest.raises(_ProcessDeath):
            run_extraction_workflow(
                WorkflowState(request=request, evidence=_evidence()),
                _postgres_deps(conn, first),
            )
        # Rewrite a committed stage's output, leaving output_hash describing the
        # original — the state a corrupted backup or a bad hand-edit produces.
        updated = conn.execute(
            """
            UPDATE extraction_run_steps
               SET output = jsonb_set(
                       output, '{tampered}', '"not what the stage produced"'::jsonb, true)
             WHERE org_id = %s AND run_id = %s AND status = 'succeeded'
               AND step_name = 'classify'
            """,
            (_ORG, run_id),
        )
        assert updated.rowcount == 1, "no committed classify step to tamper with"

    with psycopg.connect(extraction_db_url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        second = _CountingLLM()
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(fresh_conn, second),
        )
        rejected = fresh_conn.execute(
            """
            SELECT count(*) FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'step_failed'
               AND payload->'error'->>'code' = 'checkpoint_rejected'
               AND payload->>'reason' = 'checkpoint_hash_mismatch'
            """,
            (_ORG, run_id),
        ).fetchone()

    assert second.calls >= 1, "the tampered checkpoint was trusted instead of re-run"
    assert rejected is not None and rejected[0] >= 1, "the rejection was not recorded"
    assert final.status == "waiting_review"


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_step_commit_and_its_event_are_one_transaction(extraction_db_url: str) -> None:
    """If the event append fails, the step row must not be durable either.

    This is the fix itself rather than its safety net: with the pair inside one
    `conn.transaction()`, a failure in the window rolls back the step row, so the
    stage is simply not checkpointed and re-runs normally.
    """
    run_id = str(uuid.uuid4())
    request = _request(run_id)

    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=run_id, org_id=_ORG)
        events = _ExplodingEventStore(conn=conn)
        events.fail_on_step = _TORN_STEP
        checkpoint = PostgresCheckpointStore(conn=conn)
        with pytest.raises(RuntimeError, match="injected event-append failure"):
            run_extraction_workflow(
                WorkflowState(request=request, evidence=_evidence()),
                WorkflowDeps(
                    structured_llm=_CountingLLM(),
                    checkpoint=checkpoint,
                    events=events,
                    persist=PostgresPersistStore(conn),
                    evidence_loader=lambda _r: _evidence(),
                ),
            )

        rows = conn.execute(
            """
            SELECT count(*) FROM extraction_run_steps
             WHERE org_id = %s AND run_id = %s AND step_name = %s
            """,
            (_ORG, run_id, _TORN_STEP),
        ).fetchone()
        assert rows is not None and rows[0] == 0, (
            "the step row outlived the failed event append: the two writes are still "
            "separately durable, so a crash in between can still orphan a stage output"
        )
        # The in-process cache must not answer for a rolled-back step either.
        assert (
            checkpoint.load_succeeded(
                run_id=run_id,
                org_id=_ORG,
                step_name=_TORN_STEP,
                input_hash="unused",
                workflow_version=request.workflow_version,
            )
            is None
        )
