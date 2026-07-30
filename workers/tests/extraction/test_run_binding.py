"""The durable run must be bound to its immutable ``extraction_runs`` record.

``handle_extraction_run`` used to take every pin from the queue payload —
``as_of``, ``corpus_version_id``, ``provider``, ``model``, ``policy_id`` and all
five ``max_*`` budgets — and the extraction package issued exactly ONE read of
``extraction_runs`` (``load_usage``), which selects only the four usage
counters. No pin was ever compared, so under a real ``run_id`` a payload could
declare a different cutoff, a different corpus and a 250x budget and the run
would proceed on those, while the row a reviewer reads still advertised the
original pins. 0004's own ``CHECK (max_calls BETWEEN 1 AND 10)`` and ``CHECK
(max_cost_usd <= 2.0)`` were bypassed for the same reason: the columns carrying
them are never read.

Evidence was unbound in the same way: ``_evidence_from_payload`` computed
``text_hash`` from the payload's OWN text, and ``source_spans`` was never
SELECTed anywhere in ``workers/src``, so fabricated text under a real span id
verified against itself. The composite FK proves the span EXISTS, never that
the text is the text that span addresses.

Runs against the isolated ``<db>_extraction`` sibling for the reason documented
in ``test_postgres_crash_resume``: 0004 makes ``extraction_runs`` rows
permanent, so they cannot be torn down.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.errors import ExtractionError
from fel_workers.extraction.handler import handle_extraction_run
from fel_workers.extraction.hashing import sha256_hex

from .conftest import FIXTURE_DOC, FIXTURE_SPAN
from .test_postgres_crash_resume import _CORPUS as _SEEDED_CORPUS
from .test_postgres_crash_resume import _ENTITY as _SEEDED_ENTITY
from .test_postgres_crash_resume import (
    _ORG,
    _POLICY,
    _USER,
    _WORKSPACE,
    LONG_SPAN_TEXT,
    _seed_parents,
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


# The document `_seed_parents` creates is published at now(), so a run whose
# as_of precedes it would fail the cutoff guard on canonical dates. Every run
# seeded here is pinned well after it so the assertions isolate their target.
_AS_OF = datetime(2026, 12, 31, tzinfo=UTC)


def _seed_run(conn: psycopg.Connection, run_id: str, **pins: Any) -> dict[str, Any]:
    """Insert one queued ``extraction_runs`` row and return the pins it carries."""
    row: dict[str, Any] = {
        "modes": ["kpi"],
        "as_of": _AS_OF,
        "corpus_version_id": _SEEDED_CORPUS,
        "ontology_version": "saas-metrics/v1",
        "workflow_version": "extraction-workflow/v1",
        "provider": "mock",
        "model": "mock-structured-v1",
        "policy_id": _POLICY,
        "input_hash": sha256_hex(f"manifest|{run_id}"),
        "max_calls": 10,
        "max_input_tokens": 100_000,
        "max_output_tokens": 20_000,
        "max_cost_usd": "2.0",
        "max_wall_seconds": 600,
    }
    row.update(pins)
    conn.execute(
        """
        INSERT INTO extraction_runs (
            id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
            ontology_version, workflow_version, provider, model, policy_id,
            input_hash, idempotency_key, created_by, status,
            max_calls, max_input_tokens, max_output_tokens, max_cost_usd,
            max_wall_seconds
        ) VALUES (
            %(id)s,%(org)s,%(ws)s,%(entity)s,%(modes)s,%(as_of)s,%(corpus_version_id)s,
            %(ontology_version)s,%(workflow_version)s,%(provider)s,%(model)s,%(policy_id)s,
            %(input_hash)s,%(idem)s,%(user)s,'queued',
            %(max_calls)s,%(max_input_tokens)s,%(max_output_tokens)s,%(max_cost_usd)s,
            %(max_wall_seconds)s
        )
        """,
        {
            "id": run_id,
            "org": _ORG,
            "ws": _WORKSPACE,
            "entity": _SEEDED_ENTITY,
            "idem": f"run-binding|{run_id}",
            "user": _USER,
            **row,
        },
    )
    return row


def _payload(run_id: str, **overrides: Any) -> dict[str, Any]:
    """A payload that agrees with the seeded row unless an override diverges."""
    payload: dict[str, Any] = {
        "run_id": run_id,
        "org_id": _ORG,
        "workspace_id": _WORKSPACE,
        "entity_id": _SEEDED_ENTITY,
        "modes": ["kpi"],
        "as_of": _AS_OF.isoformat(),
        "corpus_version_id": _SEEDED_CORPUS,
        "ontology_version": "saas-metrics/v1",
        "workflow_version": "extraction-workflow/v1",
        "provider": "mock",
        "model": "mock-structured-v1",
        "policy_id": _POLICY,
        "input_hash": sha256_hex(f"manifest|{run_id}"),
        "issuer_label": "Example SaaS",
        "evidence": [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "text": LONG_SPAN_TEXT,
                "text_hash": sha256_hex(LONG_SPAN_TEXT),
                "published_at": "2026-06-30T00:00:00+00:00",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _durable(conn: psycopg.Connection, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
          (SELECT status FROM extraction_runs WHERE id = %(run)s),
          (SELECT count(*) FROM extraction_proposals WHERE run_id = %(run)s)
        """,
        {"run": run_id},
    ).fetchone()
    assert row is not None
    return {"status": row[0], "proposals": row[1]}


@requires_db
def test_payload_may_not_redeclare_the_runs_pins(extraction_db_url: str) -> None:
    """A payload that contradicts the run row must be refused, not obeyed.

    The row here is a REAL run pinned to a 2026 cutoff, the seeded corpus and a
    USD 0.50 / 3-call budget. The payload claims a 2027 cutoff, a different
    corpus and a USD 500 / 99-call budget — the exact shape that ran to
    ``waiting_review`` and persisted a proposal while the row still advertised
    its original pins, admitting evidence published a year past the run's true
    cutoff (look-ahead bias in a pinned run) and bypassing 0004's budget CHECKs
    by never reading the columns that carry them.
    """
    run_id = str(uuid.uuid4())
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, run_id, max_calls=3, max_cost_usd="0.5")

        with pytest.raises(ExtractionError) as excinfo:
            handle_extraction_run(
                conn,
                MockStructuredLLMProvider(),
                _payload(
                    run_id,
                    as_of=datetime(2027, 12, 31, tzinfo=UTC).isoformat(),
                    corpus_version_id=str(uuid.uuid4()),
                    max_calls=99,
                    max_cost_usd="500",
                ),
                job_org_id=_ORG,
            )
        durable = _durable(conn, run_id)

    assert excinfo.value.code == "run_pin_mismatch", excinfo.value
    message = str(excinfo.value)
    for pin in ("as_of", "corpus_version_id", "max_calls", "max_cost_usd"):
        assert pin in message, f"{pin} divergence was not named: {message}"
    assert durable["status"] == "queued", "a contradicted run was started anyway"
    assert durable["proposals"] == 0, "a contradicted run persisted proposals"


@requires_db
def test_absent_payload_pins_are_taken_from_the_run_row(extraction_db_url: str) -> None:
    """Omitted pins bind to the record rather than to a handler default.

    ``request_from_payload`` defaults ``as_of`` to ``now()``, ``provider`` to
    ``mock``, ``corpus_version_id`` to the entity id and every budget to the
    ADR-0007 maximum. On the durable path those defaults are not the run's
    pins — the row is — so a minimal payload must run on the row's values, and
    the row's tighter budget must be the one that binds.
    """
    run_id = str(uuid.uuid4())
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        seeded = _seed_run(conn, run_id, max_calls=4, max_cost_usd="0.75")

        state = handle_extraction_run(
            conn,
            MockStructuredLLMProvider(),
            {
                "run_id": run_id,
                "org_id": _ORG,
                "workspace_id": _WORKSPACE,
                "entity_id": _SEEDED_ENTITY,
                "evidence": _payload(run_id)["evidence"],
            },
            job_org_id=_ORG,
        )

    assert state.request.as_of == seeded["as_of"]
    assert state.request.corpus_version_id == str(_SEEDED_CORPUS)
    assert state.request.policy_id == str(_POLICY)
    assert state.request.input_hash == seeded["input_hash"]
    assert state.request.max_calls == 4, "the run's own call cap was not applied"
    assert state.request.max_cost_usd == Decimal("0.75"), "the run's own cost cap was not applied"
    assert state.status == "waiting_review"


@requires_db
def test_fabricated_evidence_text_under_a_real_span_is_refused(extraction_db_url: str) -> None:
    """Evidence text must verify against the canonical ``source_spans`` hash.

    ``_evidence_from_payload`` hashed the payload's own text, so the integrity
    check in ``_stage_assemble_evidence`` compared a payload against itself and
    always passed. ``source_spans`` is never SELECTed anywhere in
    ``workers/src`` (only INSERTed by ``ingestion/``), so the stored hash — the
    citation's real content address — was never consulted. The composite FK
    checks that the span EXISTS, not what it says: this payload cites a real,
    seeded span and puts words in its mouth.
    """
    run_id = str(uuid.uuid4())
    fabricated = "ARR was $999 billion as of June 30, 2026."
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, run_id)

        payload = _payload(run_id)
        payload["evidence"] = [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "text": fabricated,
                # No text_hash: the handler self-hashed, which is the defect.
                "published_at": "2026-06-30T00:00:00+00:00",
            }
        ]
        with pytest.raises(ExtractionError) as excinfo:
            handle_extraction_run(conn, MockStructuredLLMProvider(), payload, job_org_id=_ORG)
        durable = _durable(conn, run_id)

    assert excinfo.value.code == "integrity_error", excinfo.value
    assert FIXTURE_SPAN in str(excinfo.value)
    assert durable["proposals"] == 0, "a proposal cited a span it had fabricated the text of"


@requires_db
def test_evidence_citing_an_unknown_span_is_refused(extraction_db_url: str) -> None:
    """A span id with no canonical row cannot be verified, so it fails closed."""
    run_id = str(uuid.uuid4())
    ghost = str(uuid.uuid4())
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, run_id)

        payload = _payload(run_id)
        payload["evidence"] = [
            {
                "source_span_id": ghost,
                "document_version_id": FIXTURE_DOC,
                "text": LONG_SPAN_TEXT,
                "text_hash": sha256_hex(LONG_SPAN_TEXT),
            }
        ]
        with pytest.raises(ExtractionError) as excinfo:
            handle_extraction_run(conn, MockStructuredLLMProvider(), payload, job_org_id=_ORG)

    assert excinfo.value.code == "integrity_error", excinfo.value
    assert ghost in str(excinfo.value)


@requires_db
def test_evidence_pointing_at_the_wrong_document_version_is_refused(
    extraction_db_url: str,
) -> None:
    """The span's canonical document version is not the payload's to assert."""
    run_id = str(uuid.uuid4())
    with psycopg.connect(extraction_db_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (_ORG,))
        _seed_parents(conn)
        _seed_run(conn, run_id)

        payload = _payload(run_id)
        payload["evidence"] = [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": str(uuid.uuid4()),
                "text": LONG_SPAN_TEXT,
                "text_hash": sha256_hex(LONG_SPAN_TEXT),
            }
        ]
        with pytest.raises(ExtractionError) as excinfo:
            handle_extraction_run(conn, MockStructuredLLMProvider(), payload, job_org_id=_ORG)

    assert excinfo.value.code == "integrity_error", excinfo.value
    assert "document_version_id" in str(excinfo.value)


def test_memory_path_needs_no_run_row(structured_llm: MockStructuredLLMProvider) -> None:
    """The binding is scoped to the durable path.

    Memory stores write nothing and have no ``extraction_runs`` row to bind to,
    so an inline payload must keep running exactly as before — this is the smoke
    path the runbook documents.
    """
    from .conftest import sample_payload

    state = handle_extraction_run(None, structured_llm, sample_payload(modes=["kpi"]))
    assert state.status == "waiting_review"
