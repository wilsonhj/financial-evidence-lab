"""Checkpoint payload verification against the REAL Postgres stores (#158).

Crash-resume rehydrates a completed stage's result from the durable
`step_completed` event and hands it straight back to the workflow. Until #158
nothing on that path compared the restored payload to any hash: `_is_recoverable`
checked only the torn state (`output_hash` non-null, `output` None), and
`_load_stage_output` returned `payload["stage_output"]` verbatim from whichever
row was newest. Because the workflow recomputes `raw_payload_hash` /
`proposal_id_for` from the restored payload, any divergence forked the run's
proposal identity — and 0004 makes the result permanent (proposals cannot be
deleted, events cannot be deleted, a terminal run cannot be reopened).

The corruption vector needs no privileged bypass: `extraction_run_events` has
no uniqueness constraint, 0004 forbids UPDATE/DELETE but not INSERT, and the
resume reads `ORDER BY id DESC LIMIT 1`. Appending a second `step_completed` for
the same `(step_name, input_hash)` with a mutated `stage_output` is enough.

Every scenario here resumes through a FRESH store object on a FRESH connection,
because `PostgresCheckpointStore._memory` answers from cache before the row is
ever read back — the same reason `test_postgres_crash_resume.py` does. Shares
that module's seeding helpers and its isolated `<db>_extraction` sibling.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from typing import Any

import psycopg
import pytest

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.persist import (
    PostgresCheckpointStore,
    PostgresEventStore,
    PostgresPersistStore,
)
from fel_workers.extraction.types import STAGE_ORDER, ExtractionRunRequest, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .test_postgres_crash_resume import (
    _ORG,
    _CountingLLM,
    _evidence,
    _postgres_deps,
    _ProcessDeath,
    _request,
    _seed_parents,
    _seed_run,
    ensure_extraction_database,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
    pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured"),
]

# The stage whose output IS the run's product. Corrupting its checkpoint is what
# splits proposal identity; every downstream stage recomputes from it.
_STEP = "extract_kpi"
_HONEST_RAW_VALUE = "$100 million"
_MUTATED_RAW_VALUE = "$900 million"
# Issuer-supplied dimension keys that collide with `events._REDACT_KEYS`.
_COLLIDING_DIMENSIONS = {"token": "FY25", "raw": "as-reported"}


@pytest.fixture(scope="module")
def extraction_db_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL not configured")
    return ensure_extraction_database(TEST_DATABASE_URL)


# ---------------------------------------------------------------------------
# Injection helpers
# ---------------------------------------------------------------------------


@dataclass
class _DyingCheckpointStore(PostgresCheckpointStore):
    """Dies right AFTER one step's commit lands.

    `commit_succeeded_atomic` has returned, so the step row and its
    `step_completed` event are durable. The death derives from BaseException so
    no handler runs and the run row stays `running` — exactly the state the
    #158 scenarios start from ("die right after `extract_kpi` commits").
    """

    die_after_step: str = ""

    def commit_succeeded_atomic(self, **kwargs: Any) -> Any:
        committed = super().commit_succeeded_atomic(**kwargs)
        if kwargs["record"].step_name == self.die_after_step:
            raise _ProcessDeath(f"simulated process death after {self.die_after_step} committed")
        return committed


@dataclass
class _LegacyEventStore(PostgresEventStore):
    """Writes `step_completed` events shaped as the pre-#158 code wrote them.

    Strips the additive `stage_output_hash` key, so the durable row is exactly
    what every run committed before the field existed.
    """

    def append(self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> Any:
        if event_type == "step_completed":
            payload = {k: v for k, v in payload.items() if k != "stage_output_hash"}
        return super().append(org_id=org_id, run_id=run_id, event_type=event_type, payload=payload)


class _CollidingDimensionsLLM(_CountingLLM):
    """Mock whose KPI proposal carries dimension keys named like secrets.

    `dimensions` holds issuer-supplied keys with arbitrary names (the contract
    schema types it `additionalProperties: {"type": "string"}`), so a filing can
    legitimately produce a key called `token` or `raw`.
    """

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = super().generate_structured(request)
        if request.schema_name != "kpi" or not isinstance(result.parsed, dict):
            return result
        parsed = json.loads(json.dumps(result.parsed))
        for proposal in parsed["proposals"]:
            proposal["dimensions"] = dict(_COLLIDING_DIMENSIONS)
        return replace(result, parsed=parsed)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _run_status(conn: psycopg.Connection[Any], run_id: str) -> str:
    row = conn.execute("SELECT status FROM extraction_runs WHERE id = %s", (run_id,)).fetchone()
    assert row is not None, "run row missing"
    return str(row[0])


def _terminal_event_count(conn: psycopg.Connection[Any], run_id: str) -> int:
    row = conn.execute(
        """
        SELECT count(*) FROM extraction_run_events
         WHERE org_id = %s AND run_id = %s
           AND event_type IN ('run_failed', 'run_succeeded', 'run_cancelled')
        """,
        (_ORG, run_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _proposals(conn: psycopg.Connection[Any], run_id: str) -> list[tuple[str, str, str]]:
    """`(metric_id, raw_value, raw_payload_hash)` for every proposal of ONE run."""
    rows = conn.execute(
        """
        SELECT metric_id, payload->>'raw_value', raw_payload_hash
          FROM extraction_proposals
         WHERE org_id = %s AND run_id = %s
         ORDER BY raw_payload_hash
        """,
        (_ORG, run_id),
    ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def _newest_step_completed(
    conn: psycopg.Connection[Any], run_id: str, step_name: str
) -> dict[str, Any]:
    """The row `_load_stage_output` would read: newest `step_completed` for the step."""
    row = conn.execute(
        """
        SELECT payload FROM extraction_run_events
         WHERE org_id = %s AND run_id = %s AND event_type = 'step_completed'
           AND payload->>'step_name' = %s
         ORDER BY id DESC LIMIT 1
        """,
        (_ORG, run_id, step_name),
    ).fetchone()
    assert row is not None, f"no step_completed event for {step_name}"
    payload = row[0]
    return json.loads(payload) if isinstance(payload, str) else dict(payload)


def _step_row_output_hash(conn: psycopg.Connection[Any], run_id: str, step_name: str) -> str | None:
    row = conn.execute(
        """
        SELECT output_hash FROM extraction_run_steps
         WHERE org_id = %s AND run_id = %s AND step_name = %s AND status = 'succeeded'
        """,
        (_ORG, run_id, step_name),
    ).fetchone()
    assert row is not None, f"no succeeded step row for {step_name}"
    return None if row[0] is None else str(row[0])


def _append_step_completed(
    conn: psycopg.Connection[Any], run_id: str, payload: dict[str, Any]
) -> None:
    """The corruption vector.

    INSERT is the one write 0004 leaves open on `extraction_run_events`: the
    table is append-only (no UPDATE, no DELETE) and has no uniqueness constraint,
    so a second `step_completed` for the same `(step_name, input_hash)` lands,
    and it is the row `ORDER BY id DESC LIMIT 1` hands to the resume.
    """
    conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
    conn.execute(
        """
        INSERT INTO extraction_run_events (org_id, run_id, event_type, payload)
        VALUES (%s, %s, 'step_completed', %s::jsonb)
        """,
        (_ORG, run_id, json.dumps(payload)),
    )


def _mutated(payload: dict[str, Any]) -> dict[str, Any]:
    """A verbatim copy of the event payload with ONE proposal value altered.

    `output_hash` (and, once it exists, `stage_output_hash`) are left exactly
    as written: this models divergence of the payload from the hashes that were
    recorded for it — bit rot, an errant repair script, replication skew — not
    an actor who rewrites the hashes to match.
    """
    mutated: dict[str, Any] = json.loads(json.dumps(payload))
    proposal = mutated["stage_output"]["proposals"][0]
    assert proposal["raw_value"] == _HONEST_RAW_VALUE, "fixture drift: the mock KPI changed"
    proposal["raw_value"] = _MUTATED_RAW_VALUE
    return mutated


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------


def _crash_after(
    conn: psycopg.Connection[Any],
    request: ExtractionRunRequest,
    *,
    step: str,
    llm: _CountingLLM | None = None,
    events: PostgresEventStore | None = None,
) -> _CountingLLM:
    """Seed the run and drive it until `step` has committed, then die."""
    _seed_parents(conn)
    _seed_run(conn, request)
    PostgresPersistStore(conn).mark_running(run_id=request.run_id, org_id=_ORG)
    llm = llm or _CountingLLM()
    with pytest.raises(_ProcessDeath):
        run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            WorkflowDeps(
                structured_llm=llm,
                checkpoint=_DyingCheckpointStore(conn=conn, die_after_step=step),
                events=events or PostgresEventStore(conn=conn),
                persist=PostgresPersistStore(conn),
                evidence_loader=lambda _r: _evidence(),
            ),
        )
    assert _run_status(conn, request.run_id) == "running", "death must leave the run resumable"
    assert _step_row_output_hash(conn, request.run_id, step) is not None
    return llm


def _resume(url: str, request: ExtractionRunRequest) -> tuple[WorkflowState, _CountingLLM]:
    """Process death: nothing survives but the database. Fresh stores, fresh connection."""
    with psycopg.connect(url, autocommit=True) as fresh_conn:
        fresh_conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        llm = _CountingLLM()
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(fresh_conn, llm),
        )
    return final, llm


@pytest.fixture(scope="module")
def baseline(extraction_db_url: str) -> list[tuple[str, str, str]]:
    """Proposals of an UNINTERRUPTED run, the identity every resume must reproduce.

    `raw_payload_hash` is `hash_json` over the proposal payload and carries no
    run id, so it is comparable across runs — which is what lets a resumed run
    be checked against a clean one rather than against "an error was raised".
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=request.run_id, org_id=_ORG)
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(conn, _CountingLLM()),
        )
        assert final.status == "waiting_review"
        proposals = _proposals(conn, request.run_id)
    assert proposals, "the baseline run persisted no proposals"
    assert all(raw == _HONEST_RAW_VALUE for _, raw, _ in proposals), proposals
    return proposals


@pytest.fixture(scope="module")
def three_mode_run_id(extraction_db_url: str) -> str:
    """One uninterrupted run through every entry of STAGE_ORDER (no mode skipped)."""
    request = replace(_request(str(uuid.uuid4())), modes=("kpi", "guidance", "revenue_driver"))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _seed_parents(conn)
        _seed_run(conn, request)
        PostgresPersistStore(conn).mark_running(run_id=request.run_id, org_id=_ORG)
        final = run_extraction_workflow(
            WorkflowState(request=request, evidence=_evidence()),
            _postgres_deps(conn, _CountingLLM()),
        )
        assert final.status == "waiting_review"
        committed = {
            str(r[0])
            for r in conn.execute(
                """
                SELECT step_name FROM extraction_run_steps
                 WHERE org_id = %s AND run_id = %s AND status = 'succeeded'
                """,
                (_ORG, request.run_id),
            ).fetchall()
        }
    assert committed == set(STAGE_ORDER), sorted(set(STAGE_ORDER) - committed)
    return request.run_id


# ---------------------------------------------------------------------------
# Criterion 1 / Scenario A — a mutated durable payload must not fork identity.
# ---------------------------------------------------------------------------


def test_mutated_durable_checkpoint_does_not_fork_proposal_identity(
    extraction_db_url: str, baseline: list[tuple[str, str, str]]
) -> None:
    """Resume after the `extract_kpi` payload was altered post-commit.

    Before the fix the resumed run completed `waiting_review` with a proposal
    whose `raw_value` was `$900 million` and whose `raw_payload_hash` /
    `proposal_id` differed from the clean baseline — no error, no event, no
    telemetry. Asserted as hash EQUALITY with the baseline, not as "something
    was raised".
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _crash_after(conn, request, step=_STEP)
        honest = _newest_step_completed(conn, request.run_id, _STEP)
        _append_step_completed(conn, request.run_id, _mutated(honest))
        # Precondition: the corruption is what the resume will read first.
        newest = _newest_step_completed(conn, request.run_id, _STEP)
        assert newest["stage_output"]["proposals"][0]["raw_value"] == _MUTATED_RAW_VALUE
        assert newest["output_hash"] == honest["output_hash"]

    final, _ = _resume(extraction_db_url, request)

    assert final.status == "waiting_review"
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        resumed = _proposals(conn, request.run_id)
    assert {h for _, _, h in resumed} == {h for _, _, h in baseline}, (
        "the resumed run's proposal identity diverged from an uninterrupted run: "
        f"resumed={resumed} baseline={baseline}"
    )
    assert all(raw == _HONEST_RAW_VALUE for _, raw, _ in resumed), resumed


# ---------------------------------------------------------------------------
# Criterion 3 — mismatch ⇒ the stage re-runs; the run never goes terminal.
# ---------------------------------------------------------------------------


def test_mismatch_reruns_the_stage_and_never_makes_the_run_terminal(
    extraction_db_url: str,
) -> None:
    """`_is_recoverable → False`, not `IntegrityError`.

    An exception would take the `StepFailed` branch and land the run terminal
    `failed`, which 0004 makes permanent and #146 makes unretryable: a corrupted
    checkpoint would kill the run outright. Re-running the stage is the
    fail-closed answer the torn-state precedent already set; it costs model
    calls bounded by `RunBudget` and converges.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        first = _crash_after(conn, request, step=_STEP)
        _append_step_completed(
            conn, request.run_id, _mutated(_newest_step_completed(conn, request.run_id, _STEP))
        )

    final, second = _resume(extraction_db_url, request)

    assert second.calls >= 1, (
        "the corrupted checkpoint was accepted: the stage was resumed with zero "
        f"model calls instead of re-run (crashed={first.calls}, resumed={second.calls})"
    )
    assert final.status == "waiting_review"
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        assert _run_status(conn, request.run_id) == "waiting_review"
        assert (
            _terminal_event_count(conn, request.run_id) == 0
        ), "the run passed through a terminal state on the mismatch path"


# ---------------------------------------------------------------------------
# Criterion 2 / Scenario B — crash after persist, corrupt upstream: ONE proposal.
# ---------------------------------------------------------------------------


def test_crash_after_persist_plus_upstream_corruption_leaves_one_proposal(
    extraction_db_url: str, baseline: list[tuple[str, str, str]]
) -> None:
    """Duplicate, contradictory proposals for one run and one metric.

    With the honest proposals already durable, a resume that accepts a mutated
    `extract_kpi` payload computes a different `proposal_ids` list, so
    `persist_proposals`' `stage_input_hash` misses its replay key, the stage
    re-runs and INSERTs `$900 million` beside `$100 million` — both
    `needs_review`, neither deletable, and the pair frozen forever the moment
    the run goes terminal.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        _crash_after(conn, request, step="persist_proposals")
        assert len(_proposals(conn, request.run_id)) == len(baseline)
        _append_step_completed(
            conn, request.run_id, _mutated(_newest_step_completed(conn, request.run_id, _STEP))
        )

    final, _ = _resume(extraction_db_url, request)

    assert final.status == "waiting_review"
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        resumed = _proposals(conn, request.run_id)
    assert (
        len(resumed) == len(baseline) == 1
    ), f"the resumed run inserted a divergent proposal beside the honest one: {resumed}"
    assert {h for _, _, h in resumed} == {h for _, _, h in baseline}


# ---------------------------------------------------------------------------
# Criterion 4 — a coherent competing event that disagrees with the step ROW.
# ---------------------------------------------------------------------------


def test_competing_newest_event_disagreeing_with_the_step_row_is_not_the_checkpoint(
    extraction_db_url: str, baseline: list[tuple[str, str, str]]
) -> None:
    """Regression for the `ORDER BY id DESC LIMIT 1` hazard `_commit_fence` documents.

    This competitor is internally COHERENT — its `output_hash` and
    `stage_output_hash` both describe its mutated payload — so the payload
    check alone would accept it. What rejects it is that its `output_hash`
    disagrees with the step row's `output_hash` COLUMN: a different table, a
    different guard, frozen once the run is terminal. The honest event, though
    older, is the one the resume must use.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        first = _crash_after(conn, request, step=_STEP)
        honest = _newest_step_completed(conn, request.run_id, _STEP)
        competing = _mutated(honest)
        competing["output_hash"] = hash_json(competing["stage_output"])
        competing["stage_output_hash"] = hash_json(competing["stage_output"])
        assert competing["output_hash"] != _step_row_output_hash(conn, request.run_id, _STEP)
        _append_step_completed(conn, request.run_id, competing)
        newest = _newest_step_completed(conn, request.run_id, _STEP)
        assert newest["output_hash"] == competing["output_hash"], "competitor is not newest"

    final, second = _resume(extraction_db_url, request)

    assert final.status == "waiting_review"
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        resumed = _proposals(conn, request.run_id)
    assert all(raw == _HONEST_RAW_VALUE for _, raw, _ in resumed), (
        "the newest event was used as the checkpoint although it disagrees with the "
        f"step row: {resumed}"
    )
    assert {h for _, _, h in resumed} == {h for _, _, h in baseline}
    # Binding the read to the row keeps the HONEST checkpoint usable: the stage
    # is restored from it rather than re-run.
    assert second.calls == 0, (
        "the honest event was discarded along with the competitor "
        f"(crashed={first.calls}, resumed={second.calls})"
    )


# ---------------------------------------------------------------------------
# Criterion 5 — rows written before the field existed resume exactly as today.
# ---------------------------------------------------------------------------


def test_legacy_event_without_the_field_resumes_exactly_as_today(
    extraction_db_url: str, baseline: list[tuple[str, str, str]]
) -> None:
    """No `stage_output_hash` ⇒ no check: the checkpoint is honoured, not re-run."""
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        first = _crash_after(conn, request, step=_STEP, events=_LegacyEventStore(conn=conn))
        legacy = _newest_step_completed(conn, request.run_id, _STEP)
        assert "stage_output_hash" not in legacy, "the seeded event is not legacy-shaped"
        assert legacy["output_hash"] is not None

    final, second = _resume(extraction_db_url, request)

    assert final.status == "waiting_review"
    assert second.calls == 0, (
        "a legacy checkpoint was re-run instead of restored "
        f"(crashed={first.calls}, resumed={second.calls})"
    )
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        resumed = _proposals(conn, request.run_id)
    assert {h for _, _, h in resumed} == {h for _, _, h in baseline}


# ---------------------------------------------------------------------------
# Criterion 6 — the latent trap is pinned: every stage is hash-stable.
# ---------------------------------------------------------------------------


def test_every_stage_output_is_hash_stable_through_the_durable_row(
    extraction_db_url: str, three_mode_run_id: str
) -> None:
    """`hash_json(durable stage_output) == output_hash` for all of STAGE_ORDER.

    `output_hash` hashes the LIVE return value; the row holds the serialized,
    redacted, jsonb-round-tripped form. They agree today only because every
    stage returns JSON-native values (E1 in #158: 12/12). A stage that starts
    returning a dataclass or a tuple would diverge — `canonical_json` hashes a
    dataclass as its `repr` while `serialize_stage_output` expands it — and
    this is where that fails loudly, at CI, rather than silently at resume.
    """
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        for step_name in STAGE_ORDER:
            row_hash = _step_row_output_hash(conn, three_mode_run_id, step_name)
            durable = _newest_step_completed(conn, three_mode_run_id, step_name)["stage_output"]
            assert hash_json(durable) == row_hash, (
                f"{step_name}: the durable stage_output no longer hashes to the step row's "
                "output_hash — a stage return value is not JSON-native"
            )


def test_every_durable_step_completed_event_carries_the_hash_of_its_payload(
    extraction_db_url: str, three_mode_run_id: str
) -> None:
    """The write side stamps `stage_output_hash` over the bytes the row holds."""
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        for step_name in STAGE_ORDER:
            payload = _newest_step_completed(conn, three_mode_run_id, step_name)
            assert payload.get("stage_output_hash") == hash_json(payload["stage_output"]), step_name


# ---------------------------------------------------------------------------
# Criterion 7 — the redaction case must not false-positive.
# ---------------------------------------------------------------------------


def test_issuer_supplied_key_colliding_with_redact_keys_still_resumes(
    extraction_db_url: str,
) -> None:
    """A `dimensions` key named `token` / `raw` must not fail a legitimate resume.

    On `main` before PR #156 the `stage_output` exemption suppressed truncation
    but not key redaction, so such a key became `"[redacted]"` in the durable
    row while the live object kept its value — a hash taken over the live
    object would have rejected an UNCORRUPTED checkpoint. #156 made the
    exemption total; this pins that the hash is taken over the redacted bytes
    so the two can never disagree again.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        first = _crash_after(conn, request, step=_STEP, llm=_CollidingDimensionsLLM())
        durable = _newest_step_completed(conn, request.run_id, _STEP)
        stored = durable["stage_output"]["proposals"][0]["dimensions"]
        assert (
            stored == _COLLIDING_DIMENSIONS
        ), f"the durable row does not hold the keys verbatim: {stored}"

    final, second = _resume(extraction_db_url, request)

    assert final.status == "waiting_review"
    assert second.calls == 0, (
        "an uncorrupted checkpoint was rejected because of a redaction-key collision "
        f"(crashed={first.calls}, resumed={second.calls})"
    )
