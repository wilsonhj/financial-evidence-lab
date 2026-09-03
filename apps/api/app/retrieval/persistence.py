"""Tenant-scoped persistence for a retrieval run's ordered trace.

Every write here honours ``db/migrations/0003_retrieval_core.sql`` exactly:
statements run on the RLS-bound tenant connection, events carry a monotonic
``seq`` per run, and the run's status walks the ADR-0006 machine with the
terminal event appended *before* the terminal status so the
``fel_guard_retrieval_run`` check passes. Only the column-scoped fields the
migration grants (status, budget_usage, cost_usd, timings_ms, finished_at,
error) are ever updated.

Reads that feed generation live here too: they are the same tenant transaction's
SELECTs, and keeping them beside the writes keeps the 0003 contract in one file.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from app.auth import TenantContext
from app.db import tenant_connection
from app.errors import api_error
from app.retrieval.providers import (
    PLANNER_VERSION,
    UnsupportedEmbeddingProvider,
    UnsupportedGenerationProvider,
    generation_pin,
)
from fel_retrieval import LaneExecutionError
from fel_retrieval.generation import ContextItem, GeneratedClaim, NumericTuple
from fel_retrieval.verification import CitationIntegrityError

# Statement-timeout applied to every retrieval connection (tenant writes and the
# per-lane corpus reads) so a pathological query can never wedge a request.
_STATEMENT_TIMEOUT = "15s"


class _RunWriter:
    """Persists one run's ordered trace on the tenant connection.

    Owns the monotonic ``seq`` allocation (matching the DB's own
    ``fel_guard_retrieval_event`` expectation) and every column-scoped run
    UPDATE, so the ADR-0006 status machine and append-only invariants are
    expressed in one place.
    """

    def __init__(self, conn: psycopg.Connection[Any], *, run_id: str, org_id: str) -> None:
        self._conn = conn
        self._run_id = run_id
        self._org_id = org_id
        self._seq = 0

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self._seq += 1
        self._conn.execute(
            "INSERT INTO retrieval_events (run_id, org_id, seq, event_type, payload)"
            " VALUES (%s, %s, %s, %s, %s::jsonb)",
            (self._run_id, self._org_id, self._seq, event_type, json.dumps(payload)),
        )

    def set_status(self, status: str) -> None:
        self._conn.execute(
            "UPDATE retrieval_runs SET status = %s WHERE id = %s",
            (status, self._run_id),
        )

    def finish_succeeded(
        self,
        *,
        budget_usage: dict[str, int],
        timings_ms: dict[str, int],
        cost_usd: Decimal,
    ) -> None:
        # Single terminal UPDATE: all columns are within the migration's
        # column-scoped grant, and run_completed is already the latest event.
        self._conn.execute(
            "UPDATE retrieval_runs SET status = 'succeeded', finished_at = now(),"
            " budget_usage = %s::jsonb, timings_ms = %s::jsonb, cost_usd = %s WHERE id = %s",
            (json.dumps(budget_usage), json.dumps(timings_ms), cost_usd, self._run_id),
        )

    def finish_abstained(
        self,
        *,
        budget_usage: dict[str, int],
        timings_ms: dict[str, int],
        cost_usd: Decimal,
    ) -> None:
        # verifying -> abstained; run_abstained is already the latest event so the
        # terminal-event guard passes. Only column-scoped grant fields are written.
        # An abstention still consumed provider tokens, so it still carries a cost.
        self._conn.execute(
            "UPDATE retrieval_runs SET status = 'abstained', finished_at = now(),"
            " budget_usage = %s::jsonb, timings_ms = %s::jsonb, cost_usd = %s WHERE id = %s",
            (json.dumps(budget_usage), json.dumps(timings_ms), cost_usd, self._run_id),
        )

    def fail(self, error: dict[str, str]) -> None:
        # Append the terminal ``run_failed`` event, then move the run to the
        # terminal ``failed`` status. ``fel_guard_retrieval_run`` allows a
        # transition to ``failed`` from any open status once ``run_failed`` is the
        # latest event; only column-scoped grant fields are written.
        self.emit("run_failed", {"error": error})
        self._conn.execute(
            "UPDATE retrieval_runs SET status = 'failed', finished_at = now(),"
            " error = %s::jsonb WHERE id = %s",
            (json.dumps(error), self._run_id),
        )


def _persist_candidates(
    conn: psycopg.Connection[Any],
    *,
    run_id: str,
    org_id: str,
    candidates: tuple[Any, ...],
    accepted: set[str],
    lane_timings: dict[str, int],
) -> None:
    for candidate in candidates:
        is_accepted = candidate.item_id in accepted
        rejection = None if is_accepted else "beyond_context_budget"
        for contribution in candidate.contributions:
            conn.execute(
                "INSERT INTO retrieval_candidates ("
                " id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank,"
                " raw_score, rrf_contribution, fused_score, fused_rank, accepted,"
                " rejection_code, timing_ms"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    org_id,
                    run_id,
                    candidate.item_id,
                    contribution.lane,
                    contribution.variant_index,
                    contribution.lane_rank,
                    contribution.raw_score,
                    contribution.rrf_contribution,
                    candidate.fused_score,
                    candidate.fused_rank,
                    is_accepted,
                    rejection,
                    lane_timings[contribution.lane],
                ),
            )


def _context_tokens(conn: psycopg.Connection[Any], item_ids: list[str]) -> int:
    if not item_ids:
        return 0
    row = conn.execute(
        "SELECT COALESCE(SUM(token_count), 0) AS tokens FROM retrieval_items"
        " WHERE id = ANY(%s::uuid[])",
        (item_ids,),
    ).fetchone()
    return int(row["tokens"]) if row else 0


def _load_context_items(conn: psycopg.Connection[Any], accepted: list[str]) -> list[ContextItem]:
    """Load the accepted context items (rank-ordered) for claim generation.

    Fact-kind items carry a checkable numeric tuple: ``value`` / ``unit`` /
    ``scale`` from ``financial_facts``, and ``period`` from the denormalized
    ``retrieval_items.period`` filter column (corpus period label; the facts
    table stores period as typed date columns, not a text label). An incomplete
    provenance tuple fails closed — never coerce NULL scale→0, drop numeric, or
    invent empty unit/period.
    """
    if not accepted:
        return []
    rows = conn.execute(
        "SELECT ri.id, ri.kind, ri.content, ri.source_span_id, ri.document_version_id,"
        " ri.financial_fact_id, ri.period AS period, ff.value, ff.unit, ff.scale"
        " FROM retrieval_items ri"
        " LEFT JOIN financial_facts ff ON ff.id = ri.financial_fact_id"
        " WHERE ri.id = ANY(%s::uuid[])",
        (accepted,),
    ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    items: list[ContextItem] = []
    for item_id in accepted:
        row = by_id.get(item_id)
        if row is None:  # pragma: no cover - accepted ids are always persisted items
            continue
        numeric = _numeric_from_fact_row(row)
        items.append(
            ContextItem(
                item_id=item_id,
                kind=row["kind"],
                text=row["content"],
                source_span_id=str(row["source_span_id"]),
                document_version_id=str(row["document_version_id"]),
                financial_fact_id=(
                    str(row["financial_fact_id"]) if row["financial_fact_id"] else None
                ),
                numeric=numeric,
            )
        )
    return items


def _numeric_from_fact_row(row: Mapping[str, Any]) -> NumericTuple | None:
    """Build a NumericTuple from a joined retrieval_items/financial_facts row.

    Returns ``None`` for non-fact items. Raises when a fact link is present but
    any provenance field is missing — silent coercion is a fail-open hazard.
    """
    if row["financial_fact_id"] is None:
        return None
    value = row["value"]
    unit = row["unit"]
    period = row["period"]
    scale = row["scale"]
    missing = [
        name
        for name, raw in (
            ("value", value),
            ("unit", unit),
            ("period", period),
            ("scale", scale),
        )
        if raw is None or (isinstance(raw, str) and not raw)
    ]
    if missing:
        raise ValueError(
            f"incomplete fact provenance for item {row['id']}: missing {', '.join(missing)}"
        )
    return NumericTuple(
        value=Decimal(value),
        unit=str(unit),
        period=str(period),
        scale=int(scale),
    )


def _persist_claims(
    conn: psycopg.Connection[Any],
    *,
    run_id: str,
    org_id: str,
    claims: tuple[GeneratedClaim, ...],
) -> None:
    """Persist claims and their citations while the run is still open.

    Honours the 0003 guards: claims are run-children inserted before the terminal
    status, and each citation targets an accepted candidate of the same run
    (``fel_guard_citation``). Confidence is stored as a decimal string.
    """
    for claim in claims:
        claim_id = str(uuid.uuid4())
        confidence = f"{claim.confidence:f}" if claim.confidence is not None else None
        conn.execute(
            "INSERT INTO claims ("
            " id, org_id, run_id, ord, text, status, confidence, calculation_lineage"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
            (
                claim_id,
                org_id,
                run_id,
                claim.ord,
                claim.text,
                claim.status,
                confidence,
                json.dumps(claim.calculation_lineage),
            ),
        )
        for citation in claim.citations:
            conn.execute(
                "INSERT INTO citations ("
                " id, org_id, run_id, claim_id, retrieval_item_id, source_span_id,"
                " status, verifier, model, version, numeric_checks, rationale"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                (
                    str(uuid.uuid4()),
                    org_id,
                    run_id,
                    claim_id,
                    citation.item_id,
                    citation.source_span_id,
                    citation.status,
                    citation.verifier,
                    citation.model,
                    citation.version,
                    json.dumps(citation.numeric_checks),
                    citation.rationale,
                ),
            )


def _resolve_index(
    conn: psycopg.Connection[Any],
    *,
    index_version_id: uuid.UUID | None,
    corpus_version_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Resolve the pinned index version (explicit pin or workspace active default)."""
    if index_version_id is not None:
        row = conn.execute(
            "SELECT id, corpus_version_id, config_hash, status, published_at,"
            " embedding_provider, embedding_model"
            " FROM retrieval_index_versions WHERE id = %s",
            (str(index_version_id),),
        ).fetchone()
        if (
            row is None
            or row["status"] not in {"ready", "superseded"}
            or row["published_at"] is None
        ):
            raise api_error(
                422, "INDEX_NOT_PUBLISHED", "index_version_id must be a published index."
            )
    else:
        row = conn.execute(
            "SELECT id, corpus_version_id, config_hash, status, published_at,"
            " embedding_provider, embedding_model"
            " FROM retrieval_index_versions WHERE is_active AND status = 'ready'"
        ).fetchone()
        if row is None:
            raise api_error(409, "NO_ACTIVE_INDEX", "No active retrieval index is available.")
    if corpus_version_id is not None and str(corpus_version_id) != str(row["corpus_version_id"]):
        raise api_error(
            422, "CORPUS_INDEX_MISMATCH", "corpus_version_id does not match the pinned index."
        )
    return dict(row)


def _insert_query(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    *,
    workspace_id: str,
    question: str,
    parent_query_id: uuid.UUID | None,
    index: dict[str, Any],
    plan_dict: dict[str, Any],
    effective_as_of: datetime,
) -> str:
    query_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO queries ("
        " id, org_id, workspace_id, created_by, question, effective_as_of,"
        " corpus_version_id, index_version_id, plan, planner_version, parent_query_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
        (
            query_id,
            ctx.org_id,
            workspace_id,
            ctx.user_id,
            question,
            effective_as_of,
            str(index["corpus_version_id"]),
            str(index["id"]),
            json.dumps(plan_dict),
            PLANNER_VERSION,
            str(parent_query_id) if parent_query_id else None,
        ),
    )
    return query_id


def _insert_run(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    *,
    query_id: str,
    index: dict[str, Any],
    mode: str,
    parent_run_id: str | None,
) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO retrieval_runs ("
        " id, org_id, query_id, parent_run_id, mode, config_hash,"
        " embedding_provider, embedding_model, generation_provider, generation_model,"
        " planner_version"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id,
            ctx.org_id,
            query_id,
            parent_run_id,
            mode,
            index["config_hash"],
            index["embedding_provider"],
            index["embedding_model"],
            *generation_pin(),
            PLANNER_VERSION,
        ),
    )
    return run_id


def _failure_envelope(exc: Exception) -> dict[str, str]:
    """Map a pipeline exception to the run's stored error envelope."""
    if isinstance(exc, UnsupportedEmbeddingProvider):
        return {"code": "EMBEDDING_PROVIDER_UNAVAILABLE", "message": str(exc)}
    if isinstance(exc, UnsupportedGenerationProvider):
        return {"code": "GENERATION_PROVIDER_UNAVAILABLE", "message": str(exc)}
    if isinstance(exc, LaneExecutionError):
        return {"code": "LANE_EXECUTION_FAILED", "message": str(exc)}
    if isinstance(exc, CitationIntegrityError):
        return {"code": exc.code, "message": str(exc)}
    return {"code": "PIPELINE_FAILED", "message": str(exc)}


def _record_run_failure(ctx: TenantContext, *, run_id: str, exc: Exception) -> None:
    """Append ``run_failed`` and move the run to ``failed`` in a fresh transaction."""
    error = _failure_envelope(exc)
    with tenant_connection(ctx) as conn:
        conn.execute("SELECT set_config('statement_timeout', %s, true)", (_STATEMENT_TIMEOUT,))
        _RunWriter(conn, run_id=run_id, org_id=ctx.org_id).fail(error)
