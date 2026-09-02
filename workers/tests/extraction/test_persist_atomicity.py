"""Proposals, their evidence and their conflicts must land as ONE transaction.

``stages.persist.stage_persist`` called ``persist_proposals`` and then ``persist_conflicts``
with nothing between them, on the worker's ``autocommit=True`` connection
(``__main__.py`` opens it that way). Each statement was therefore its own
transaction, so a failure in the second call left the first one durable:
proposals and their evidence committed, conflict membership empty, and the run
finalised ``failed``.

That state is not repairable. 0004's ``fel_guard_extraction_proposal`` calls
``fel_assert_extraction_run_open`` on the UPDATE path, so once the run row is
terminal the orphaned proposals can no longer be moved to ``rejected``, and the
guard forbids DELETE outright. The only mechanically available "repair" is
hand-inserting the missing conflict members — precisely what the
``conflict_terminal`` guard exists to prevent. So a reviewer is left with
proposals presented as independent findings when the pipeline had in fact
detected them as a conflicting group, and no way to correct or withdraw them.

``PostgresCheckpointStore.commit_succeeded_atomic`` already solves the identical
hazard for the step/event pair, with a docstring explaining it. This is the same
fix for the proposal/conflict pair.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.events import MemoryEventStore
from fel_workers.extraction.hashing import proposal_id_for, sha256_hex
from fel_workers.extraction.persist import (
    MemoryPersistStore,
    PostgresEventStore,
    PostgresPersistStore,
)
from fel_workers.extraction.types import ConflictDraft, ProposalDraft

from .conftest import FIXTURE_DOC, FIXTURE_SPAN
from .test_postgres_crash_resume import (
    _ORG,
    _WORKSPACE,
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


def _member_ids(run_id: str, drafts: list[ProposalDraft]) -> list[str]:
    """The ids ``persist_proposals`` will assign, computed the way it computes them.

    ``extraction_conflict_members.proposal_id`` carries an FK to the proposal, so
    membership can only be written for ids that exist — and inside a single
    combined write the drafts have no ``id`` yet when the conflict is built.
    """
    return [
        proposal_id_for(
            run_id=run_id,
            kind=draft.kind,
            metric_id=draft.metric_id,
            raw_payload_hash=draft.raw_payload_hash,
        )
        for draft in drafts
    ]


def _drafts() -> list[ProposalDraft]:
    """Two proposals of the same metric — the shape that produces a conflict."""
    return [
        ProposalDraft(
            kind="kpi",
            metric_id="arr",
            payload={"value": value, "unit": "USD"},
            raw_payload_hash=sha256_hex(f"raw|{value}"),
            definition_hash=sha256_hex("definition|arr"),
            comparability_key={"metric_id": "arr", "period": "2026-Q2"},
            record_confidence=Decimal("0.9"),
            evidence=[
                {
                    "source_span_id": FIXTURE_SPAN,
                    "document_version_id": FIXTURE_DOC,
                    "role": "supports",
                    "citation_status": "partial",
                }
            ],
        )
        for value in ("100000000", "120000000")
    ]


class _ExplodingConflictStore(PostgresPersistStore):
    """Fails the conflict write the way the ``conflict_terminal`` guard does.

    The real trigger observed in production was 0004's own guard refusing to
    attach unreviewed proposals to an already-adjudicated conflict group. What
    matters here is only that the SECOND write raises after the first succeeded,
    so the failure is injected directly rather than by seeding an adjudicated
    group — the same technique ``_ExplodingEventStore`` uses in
    ``test_postgres_crash_resume``.
    """

    def persist_conflicts(
        self, *, org_id: str, workspace_id: str, drafts: list[ConflictDraft]
    ) -> list[ConflictDraft]:
        raise StepFailed(
            "injected conflict-write failure",
            code="conflict_terminal",
        )


def _counts(conn: psycopg.Connection, run_id: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM extraction_proposals WHERE run_id = %(run)s),
          (SELECT count(*) FROM extraction_proposal_evidence e
             WHERE EXISTS (SELECT 1 FROM extraction_proposals p
                            WHERE p.id = e.proposal_id AND p.run_id = %(run)s)),
          (SELECT count(*) FROM extraction_conflict_members m
             WHERE EXISTS (SELECT 1 FROM extraction_proposals p
                            WHERE p.id = m.proposal_id AND p.run_id = %(run)s))
        """,
        {"run": run_id},
    ).fetchone()
    assert row is not None
    return {"proposals": row[0], "evidence": row[1], "members": row[2]}


@requires_db
def test_a_failed_conflict_write_leaves_no_orphaned_proposals(extraction_db_url: str) -> None:
    """The whole persist stage commits or none of it does.

    Without the transaction the proposals and their evidence were already
    durable when the conflict write raised, and the run then went terminal,
    which makes them permanently unmodifiable: a reviewer sees findings the
    pipeline had grouped as conflicting, presented as if independent.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, request)
        store = _ExplodingConflictStore(conn)
        store.mark_running(run_id=request.run_id, org_id=_ORG)

        drafts = _drafts()
        with pytest.raises(StepFailed, match="injected conflict-write failure"):
            store.persist_outputs_atomic(
                run_id=request.run_id,
                org_id=_ORG,
                workspace_id=_WORKSPACE,
                proposals=drafts,
                conflicts=[
                    ConflictDraft(
                        conflict_key=f"arr|{request.run_id}",
                        reason_codes=["value_disagreement"],
                        member_proposal_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
                    )
                ],
                events=PostgresEventStore(conn=conn),
            )

        counts = _counts(conn, request.run_id)

    assert counts["proposals"] == 0, (
        "proposals outlived the failed conflict write: they are now orphaned "
        "under a run that will go terminal, so 0004's run-open guard makes them "
        "permanently unmodifiable and undeletable"
    )
    assert counts["evidence"] == 0, "proposal evidence outlived the failed conflict write"
    assert counts["members"] == 0


@requires_db
def test_the_persisted_trio_is_durable_when_nothing_fails(extraction_db_url: str) -> None:
    """The transaction must still COMMIT on the happy path.

    A boundary that rolls back correctly but never commits would pass the test
    above while destroying every run.
    """
    request = _request(str(uuid.uuid4()))
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, request)
        store = PostgresPersistStore(conn)
        store.mark_running(run_id=request.run_id, org_id=_ORG)

        drafts = _drafts()
        events = PostgresEventStore(conn=conn)
        persisted, conflicts = store.persist_outputs_atomic(
            run_id=request.run_id,
            org_id=_ORG,
            workspace_id=_WORKSPACE,
            proposals=drafts,
            conflicts=[
                ConflictDraft(
                    conflict_key=f"arr|{request.run_id}",
                    reason_codes=["value_disagreement"],
                    member_proposal_ids=_member_ids(request.run_id, drafts),
                )
            ],
            events=events,
        )
        counts = _counts(conn, request.run_id)
        emitted = conn.execute(
            """
            SELECT payload FROM extraction_run_events
             WHERE org_id = %s AND run_id = %s AND event_type = 'proposals_persisted'
            """,
            (_ORG, request.run_id),
        ).fetchall()

    assert len(persisted) == 2
    assert len(conflicts) == 1
    assert counts["proposals"] == 2
    assert counts["evidence"] == 2
    assert counts["members"] == 2, "conflict membership was not written"
    assert len(emitted) == 1, "the proposals_persisted event was not written in the transaction"
    assert emitted[0][0]["count"] == 2


def test_memory_store_offers_the_same_combined_write() -> None:
    """The workflow calls one method on both paths, so the double must have it."""
    store = MemoryPersistStore()
    drafts = _drafts()
    events = MemoryEventStore()
    run_id = str(uuid.uuid4())
    persisted, conflicts = store.persist_outputs_atomic(
        run_id=run_id,
        org_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        proposals=drafts,
        conflicts=[
            ConflictDraft(
                conflict_key="arr|memory",
                reason_codes=["value_disagreement"],
                member_proposal_ids=_member_ids(run_id, drafts),
            )
        ],
        events=events,
    )
    assert len(persisted) == 2
    assert len(conflicts) == 1
    assert [e.event_type for e in events.events] == ["proposals_persisted"]


def test_a_proposal_escaping_needs_review_aborts_the_whole_write() -> None:
    """The no-auto-approve check must sit inside the boundary, not after it."""

    class _Approved(ProposalDraft):
        @property
        def state(self) -> Any:
            return "accepted"

        def __init__(self, base: ProposalDraft) -> None:
            super().__init__(
                kind=base.kind,
                metric_id=base.metric_id,
                payload=base.payload,
                raw_payload_hash=base.raw_payload_hash,
                definition_hash=base.definition_hash,
                comparability_key=base.comparability_key,
            )

    store = MemoryPersistStore()
    # `_ensure_needs_review` (ValueError) fires first; the combined write carries
    # its own StepFailed as defence in depth. Either is the invariant holding.
    with pytest.raises((ValueError, StepFailed), match="needs_review"):
        store.persist_outputs_atomic(
            run_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            workspace_id=str(uuid.uuid4()),
            proposals=[_Approved(_drafts()[0])],
            conflicts=[],
            events=MemoryEventStore(),
        )
