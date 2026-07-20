"""Observable hybrid retrieval API (M2-015 / T0206, ADR-0006).

This module wires the frozen retrieval contract (openapi v0.3.0) to the pinned
pipeline in ``fel_retrieval``: it captures an immutable query plan, executes the
lanes -> fusion pipeline once, and persists the whole run as an ordered,
replayable trace (events, per-lane candidate contributions, run timings and
budget usage) inside a single tenant transaction.

Persistence honours ``db/migrations/0003_retrieval_core.sql`` exactly:

* All tenant writes go through ``tenant_connection`` (``fel_app`` + org claims)
  so row-level security is active — a caller only ever sees its own org's
  queries/runs/events/candidates, and a cross-org id is a natural 404.
* Events carry a monotonic ``seq`` per run and are **committed before** any SSE
  emission (emission happens in a separate GET request, after the create
  transaction has committed), so a stream never shows an uncommitted event.
* The run status walks the ADR-0006 machine
  (``queued -> planning -> retrieving -> fusing -> generating -> verifying ->
  succeeded``); the terminal transition is emitted as ``run_completed`` first so
  the ``fel_guard_retrieval_run`` terminal-event check passes, and only the
  column-scoped fields the migration grants (status, budget_usage, cost_usd,
  timings_ms, finished_at, error) are ever updated.

Lane reads run over the public corpus tables (``documents``/``retrieval_*`` carry
no org_id and no RLS by design — see ``0002``/``0003``) on a dedicated read
connection with a tuple row factory, because the lane SQL in ``fel_retrieval``
consumes positional rows. Org isolation is unaffected: every org-scoped write
stays on the RLS-bound tenant connection.

Generation/verification are not part of this milestone, so runs complete with an
empty ``claims`` set; the status still walks the full machine because the schema
only admits ``succeeded`` out of ``verifying``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.auth import TenantContext
from app.config import settings
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from fel_providers import MockEmbeddingProvider
from fel_retrieval import (
    LaneQuery,
    PlannerValidationError,
    QueryRequest,
    dense_lane,
    facts_lane,
    fuse,
    lexical_lane,
    plan_query,
    tables_lane,
)
from fel_retrieval.lanes import LaneCandidate

router = APIRouter(prefix="/v1", tags=["retrieval"])

# Planner identity persisted on every query/run. Kept in one place so the query
# guard's run<->query planner-pin agreement always holds.
PLANNER_VERSION = "synonym-planner/v1"

EVENT_SCHEMA_VERSION = "retrieval-event/v1"

# Fixed lane fusion order (mirrors fel_retrieval.fusion.LANE_ORDER); lanes are
# executed and emitted in this order so a trace is deterministic.
_LANE_ORDER: tuple[str, ...] = ("dense", "lexical", "facts", "tables")
_LANE_FUNCS: dict[str, Callable[[Any, LaneQuery], list[LaneCandidate]]] = {
    "dense": dense_lane,
    "lexical": lexical_lane,
    "facts": facts_lane,
    "tables": tables_lane,
}

# SSE keep-alive comment. Emitted at stream open (and, for a still-open run,
# between polls) so a client sees liveness within the contract's 15-30s window.
_HEARTBEAT = ": keep-alive\n\n"


class CreateQuery(BaseModel):
    """Request body for creating an immutable query (contract CreateQuery)."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    parent_query_id: uuid.UUID | None = None
    as_of: AwareDatetime | None = None
    corpus_version_id: uuid.UUID | None = None
    index_version_id: uuid.UUID | None = None
    lanes: list[str] | None = Field(default=None, max_length=4)
    top_k: int | None = Field(default=None, ge=1, le=100)
    forms: list[str] | None = Field(default=None, max_length=20)
    periods: list[str] | None = Field(default=None, max_length=20)


class EvidenceFeedback(BaseModel):
    """Request body for append-only evidence feedback (contract EvidenceFeedback)."""

    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    label: str
    reason: str | None = Field(default=None, max_length=2000)
    supersedes_feedback_id: uuid.UUID | None = None


_FEEDBACK_LABELS = frozenset({"relevant", "irrelevant", "duplicate", "temporally_invalid"})


# --- Idempotency ------------------------------------------------------------
def _idempotent_replay(
    conn: psycopg.Connection[Any], ctx: TenantContext, endpoint: str, key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT response_body FROM idempotency_keys"
        " WHERE key = %s AND org_id = %s AND endpoint = %s",
        (key, ctx.org_id, endpoint),
    ).fetchone()
    return dict(row["response_body"]) if row else None


def _idempotent_store(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    endpoint: str,
    key: str,
    status: int,
    body: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO idempotency_keys (key, org_id, endpoint, response_status, response_body)"
        " VALUES (%s, %s, %s, %s, %s)",
        (key, ctx.org_id, endpoint, status, json.dumps(body)),
    )


# --- Pipeline execution + persistence --------------------------------------
def _parse_iso(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


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

    def finish_succeeded(self, *, budget_usage: dict[str, int], timings_ms: dict[str, int]) -> None:
        # Single terminal UPDATE: all columns are within the migration's
        # column-scoped grant, and run_completed is already the latest event.
        self._conn.execute(
            "UPDATE retrieval_runs SET status = 'succeeded', finished_at = now(),"
            " budget_usage = %s::jsonb, timings_ms = %s::jsonb WHERE id = %s",
            (json.dumps(budget_usage), json.dumps(timings_ms), self._run_id),
        )


def _lane_query(plan: dict[str, Any], *, effective_as_of: datetime) -> LaneQuery:
    filters = plan.get("filters", {})
    forms = filters.get("forms") or None
    periods = filters.get("periods") or None
    query_text = plan["variants"][0]
    query_vector = None
    if "dense" in plan["lanes"]:
        query_vector = MockEmbeddingProvider(512).embed([query_text])[0]
    return LaneQuery(
        index_version_id=plan["index_version_id"],
        as_of=effective_as_of,
        query_text=query_text,
        query_vector=query_vector,
        entity_id=plan["entity_ids"][0],
        forms=tuple(forms) if forms else None,
        periods=tuple(periods) if periods else None,
        corpus_version_id=plan["corpus_version_id"],
        top_k=plan["budgets"]["lane_top_k"],
    )


def _execute_pipeline(
    conn: psycopg.Connection[Any],
    read_conn: psycopg.Connection[Any],
    *,
    run_id: str,
    org_id: str,
    plan: dict[str, Any],
    mode: str,
) -> None:
    """Run lanes -> fusion once and persist the full ordered trace.

    All writes are on ``conn`` (tenant/RLS); lane SELECTs use ``read_conn``
    (public corpus, tuple rows). Everything runs inside the caller's single
    transaction, so the run either materialises fully succeeded or not at all.
    """
    writer = _RunWriter(conn, run_id=run_id, org_id=org_id)
    effective_as_of = _parse_iso(plan["effective_as_of"])
    budgets = plan["budgets"]
    lanes = [lane for lane in _LANE_ORDER if lane in plan["lanes"]]

    writer.set_status("planning")
    t0 = time.monotonic()
    writer.emit("run_started", {"mode": mode})
    writer.emit(
        "plan_ready",
        {"intent": plan["intent"], "lanes": list(plan["lanes"]), "variants": len(plan["variants"])},
    )
    planning_ms = int((time.monotonic() - t0) * 1000)

    writer.set_status("retrieving")
    t0 = time.monotonic()
    lane_query = _lane_query(plan, effective_as_of=effective_as_of)
    lane_results: dict[str, list[LaneCandidate]] = {}
    lane_timings: dict[str, int] = {}
    for lane in lanes:
        writer.emit("lane_started", {"lane": lane})
        started = time.monotonic()
        candidates = _LANE_FUNCS[lane](read_conn, lane_query)
        elapsed = int((time.monotonic() - started) * 1000)
        lane_results[lane] = candidates
        lane_timings[lane] = elapsed
        writer.emit(
            "lane_completed", {"lane": lane, "candidates": len(candidates), "timing_ms": elapsed}
        )
    retrieving_ms = int((time.monotonic() - t0) * 1000)

    writer.set_status("fusing")
    t0 = time.monotonic()
    fusion = fuse(lane_results, fused_top_k=budgets["fused_top_k"])
    context_items = budgets["context_items"]
    accepted = [c.item_id for c in fusion.candidates[:context_items]]
    accepted_set = set(accepted)
    stamp = datetime.now(UTC).isoformat()

    fusion_decisions = [
        _decision_dict(d, stamp) for d in fusion.decisions if d.stage in {"dedupe", "fusion"}
    ]
    rerank_decisions = [_decision_dict(d, stamp) for d in fusion.decisions if d.stage == "rerank"]
    writer.emit(
        "fusion_completed",
        {"fused_count": len(fusion.candidates), "decisions": fusion_decisions},
    )
    writer.emit("rerank_completed", {"reranker": "noop", "decisions": rerank_decisions})

    _persist_candidates(
        conn,
        run_id=run_id,
        org_id=org_id,
        candidates=fusion.candidates,
        accepted=accepted_set,
        lane_timings=lane_timings,
    )
    writer.emit(
        "context_selected",
        {
            "context_items": len(accepted),
            "accepted": accepted,
            "decisions": [
                {
                    "stage": "context",
                    "code": "accepted_top_k",
                    "item_ids": accepted,
                    "detail": {"context_items": context_items},
                    "occurred_at": stamp,
                }
            ],
        },
    )
    fusing_ms = int((time.monotonic() - t0) * 1000)

    writer.set_status("generating")
    writer.set_status("verifying")

    context_tokens = _context_tokens(conn, accepted)
    budget_usage = {
        "context_items": len(accepted),
        "context_tokens": context_tokens,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    timings_ms = {
        "planning": planning_ms,
        "retrieving": retrieving_ms,
        "fusing": fusing_ms,
        "total": planning_ms + retrieving_ms + fusing_ms,
    }
    writer.emit("run_completed", {"status": "succeeded"})
    writer.finish_succeeded(budget_usage=budget_usage, timings_ms=timings_ms)


def _decision_dict(decision: Any, stamp: str) -> dict[str, Any]:
    body: dict[str, Any] = decision.to_dict()
    body["occurred_at"] = stamp
    return body


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


def _corpus_read_connection() -> psycopg.Connection[Any]:
    """A tuple-row read connection over the public corpus for lane SQL.

    Corpus/retrieval tables carry no org_id and no RLS (0002/0003), so a
    plain read connection observes exactly what the pinned lanes filter to;
    all org-scoped work stays on the RLS-bound tenant connection.
    """
    url = settings().database_url
    if url is None:
        raise RuntimeError("FEL_DATABASE_URL is not configured")
    return psycopg.connect(url, autocommit=True)


# --- Query / run resolution -------------------------------------------------
def _resolve_index(conn: psycopg.Connection[Any], body: CreateQuery) -> dict[str, Any]:
    """Resolve the pinned index version (explicit pin or workspace active default)."""
    if body.index_version_id is not None:
        row = conn.execute(
            "SELECT id, corpus_version_id, config_hash, status, published_at,"
            " embedding_provider, embedding_model"
            " FROM retrieval_index_versions WHERE id = %s",
            (str(body.index_version_id),),
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
    if body.corpus_version_id is not None and str(body.corpus_version_id) != str(
        row["corpus_version_id"]
    ):
        raise api_error(
            422, "CORPUS_INDEX_MISMATCH", "corpus_version_id does not match the pinned index."
        )
    return dict(row)


def _insert_query(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    *,
    workspace_id: str,
    body: CreateQuery,
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
            body.question,
            effective_as_of,
            str(index["corpus_version_id"]),
            str(index["id"]),
            json.dumps(plan_dict),
            PLANNER_VERSION,
            str(body.parent_query_id) if body.parent_query_id else None,
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
        " embedding_provider, embedding_model, planner_version"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id,
            ctx.org_id,
            query_id,
            parent_run_id,
            mode,
            index["config_hash"],
            index["embedding_provider"],
            index["embedding_model"],
            PLANNER_VERSION,
        ),
    )
    return run_id


def _accepted_body(query_id: str, run_id: str) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "run_id": run_id,
        "events_url": f"/v1/retrieval-runs/{run_id}/events",
    }


# --- Endpoints --------------------------------------------------------------
@router.post("/workspaces/{workspace_id}/queries", status_code=202)
def create_query(
    workspace_id: uuid.UUID,
    body: CreateQuery,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    response: Response,
) -> dict[str, Any]:
    with _corpus_read_connection() as read_conn, tenant_connection(ctx) as conn:
        replay = _idempotent_replay(conn, ctx, "createQuery", idempotency_key)
        if replay is not None:
            return replay

        workspace = conn.execute(
            "SELECT id, entity_id, as_of FROM workspaces WHERE id = %s", (str(workspace_id),)
        ).fetchone()
        if workspace is None:
            raise api_error(404, "NOT_FOUND", "Workspace not found.")

        effective_as_of = workspace["as_of"]
        if body.as_of is not None:
            if body.as_of > workspace["as_of"]:
                raise api_error(422, "AS_OF_TOO_WIDE", "as_of may not widen the workspace cutoff.")
            effective_as_of = body.as_of

        index = _resolve_index(conn, body)
        try:
            plan = plan_query(
                QueryRequest(
                    question=body.question,
                    lanes=tuple(body.lanes) if body.lanes is not None else None,
                    top_k=body.top_k,
                    forms=tuple(body.forms) if body.forms is not None else None,
                    periods=tuple(body.periods) if body.periods is not None else None,
                ),
                index_version_id=str(index["id"]),
                corpus_version_id=str(index["corpus_version_id"]),
                entity_ids=[str(workspace["entity_id"])],
                effective_as_of=effective_as_of.isoformat(),
            )
        except PlannerValidationError as exc:
            raise api_error(422, exc.code, str(exc), {"field": exc.field}) from exc

        plan_dict = plan.to_dict()
        query_id = _insert_query(
            conn,
            ctx,
            workspace_id=str(workspace_id),
            body=body,
            index=index,
            plan_dict=plan_dict,
            effective_as_of=effective_as_of,
        )
        run_id = _insert_run(
            conn, ctx, query_id=query_id, index=index, mode="execute", parent_run_id=None
        )
        _execute_pipeline(
            conn, read_conn, run_id=run_id, org_id=ctx.org_id, plan=plan_dict, mode="execute"
        )

        accepted = _accepted_body(query_id, run_id)
        _idempotent_store(conn, ctx, "createQuery", idempotency_key, 202, accepted)
    response.status_code = 202
    return accepted


@router.post("/queries/{query_id}/reruns", status_code=202)
def create_query_rerun(
    query_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    response: Response,
) -> dict[str, Any]:
    with _corpus_read_connection() as read_conn, tenant_connection(ctx) as conn:
        replay = _idempotent_replay(conn, ctx, "createQueryRerun", idempotency_key)
        if replay is not None:
            return replay

        query = conn.execute(
            "SELECT id, plan, index_version_id FROM queries WHERE id = %s", (str(query_id),)
        ).fetchone()
        if query is None:
            raise api_error(404, "NOT_FOUND", "Query not found.")
        parent = conn.execute(
            "SELECT id FROM retrieval_runs WHERE query_id = %s AND mode = 'execute'"
            " ORDER BY started_at LIMIT 1",
            (str(query_id),),
        ).fetchone()
        if parent is None:
            raise api_error(409, "NO_PARENT_RUN", "Query has no execute run to rerun.")
        index = conn.execute(
            "SELECT id, corpus_version_id, config_hash, embedding_provider, embedding_model"
            " FROM retrieval_index_versions WHERE id = %s",
            (str(query["index_version_id"]),),
        ).fetchone()
        if index is None:  # pragma: no cover - query FK guarantees the index exists
            raise api_error(409, "NO_ACTIVE_INDEX", "Pinned index is unavailable.")

        run_id = _insert_run(
            conn,
            ctx,
            query_id=str(query_id),
            index=dict(index),
            mode="rerun",
            parent_run_id=str(parent["id"]),
        )
        _execute_pipeline(
            conn,
            read_conn,
            run_id=run_id,
            org_id=ctx.org_id,
            plan=dict(query["plan"]),
            mode="rerun",
        )
        accepted = _accepted_body(str(query_id), run_id)
        _idempotent_store(conn, ctx, "createQueryRerun", idempotency_key, 202, accepted)
    response.status_code = 202
    return accepted


@router.get("/queries/{query_id}")
def get_query(
    query_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        query = conn.execute(
            "SELECT id, parent_query_id, question, plan, created_at FROM queries WHERE id = %s",
            (str(query_id),),
        ).fetchone()
        if query is None:
            raise api_error(404, "NOT_FOUND", "Query not found.")
        runs = conn.execute(
            "SELECT id, parent_run_id, status, mode, started_at FROM retrieval_runs"
            " WHERE query_id = %s ORDER BY started_at, id::text",
            (str(query_id),),
        ).fetchall()
    return {
        "query_id": str(query["id"]),
        "parent_query_id": str(query["parent_query_id"]) if query["parent_query_id"] else None,
        "question": query["question"],
        "plan": query["plan"],
        "runs": [
            {
                "run_id": str(run["id"]),
                "parent_run_id": str(run["parent_run_id"]) if run["parent_run_id"] else None,
                "status": run["status"],
                "mode": run["mode"],
                "created_at": run["started_at"].isoformat(),
            }
            for run in runs
        ],
        "created_at": query["created_at"].isoformat(),
    }


def _event_body(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "run_id": run_id,
        "seq": int(row["seq"]),
        "type": row["event_type"],
        "occurred_at": row["created_at"].isoformat(),
        "payload": row["payload"],
    }


@router.get("/retrieval-runs/{run_id}")
def get_retrieval_run(
    run_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> Response:
    """Return the immutable trace, serialized byte-stably (same bytes each read)."""
    with tenant_connection(ctx, snapshot_read=True) as conn:
        run = conn.execute(
            "SELECT r.id, r.query_id, r.parent_run_id, r.status, r.config_hash,"
            " r.embedding_provider, r.embedding_model, r.generation_provider,"
            " r.generation_model, r.planner_version, r.budget_usage, r.cost_usd,"
            " r.timings_ms, r.started_at, r.finished_at,"
            " q.plan, q.corpus_version_id, q.index_version_id"
            " FROM retrieval_runs r JOIN queries q ON q.id = r.query_id AND q.org_id = r.org_id"
            " WHERE r.id = %s",
            (str(run_id),),
        ).fetchone()
        if run is None:
            raise api_error(404, "NOT_FOUND", "Retrieval run not found.")
        event_rows = conn.execute(
            "SELECT seq, event_type, payload, created_at FROM retrieval_events"
            " WHERE run_id = %s ORDER BY seq",
            (str(run_id),),
        ).fetchall()
        candidate_rows = conn.execute(
            "SELECT rc.retrieval_item_id, rc.lane, rc.variant_index, rc.lane_rank,"
            " rc.raw_score, rc.normalized_score, rc.rrf_contribution, rc.fused_score,"
            " rc.rerank_score, rc.fused_rank, rc.rerank_rank, rc.accepted,"
            " rc.rejection_code, rc.decision_detail, rc.timing_ms,"
            " ri.kind, ri.source_span_id, ri.document_version_id, d.published_at"
            " FROM retrieval_candidates rc"
            " JOIN retrieval_items ri ON ri.id = rc.retrieval_item_id"
            " JOIN documents d ON d.id = ri.document_id"
            " WHERE rc.run_id = %s"
            " ORDER BY rc.fused_rank, rc.retrieval_item_id::text",
            (str(run_id),),
        ).fetchall()

    events = [_event_body(row, str(run_id)) for row in event_rows]
    decisions: list[dict[str, Any]] = []
    for row in event_rows:
        for decision in (row["payload"] or {}).get("decisions", []):
            decisions.append(decision)

    trace = {
        "run_id": str(run["id"]),
        "query_id": str(run["query_id"]),
        "parent_run_id": str(run["parent_run_id"]) if run["parent_run_id"] else None,
        "status": run["status"],
        "plan": run["plan"],
        "lineage": {
            "corpus_version_id": str(run["corpus_version_id"]),
            "index_version_id": str(run["index_version_id"]),
            "planner_version": run["planner_version"],
            "config_hash": run["config_hash"],
            "embedding_provider": run["embedding_provider"],
            "embedding_model": run["embedding_model"],
            "generation_provider": run["generation_provider"],
            "generation_model": run["generation_model"],
        },
        "events": events,
        "candidates": _group_candidates(candidate_rows),
        "decisions": decisions,
        "claims": [],
        "timings_ms": run["timings_ms"],
        "budget_usage": run["budget_usage"],
        "cost_usd": _format_cost(run["cost_usd"]),
        "started_at": run["started_at"].isoformat(),
        "finished_at": run["finished_at"].isoformat() if run["finished_at"] else None,
    }
    canonical = json.dumps(trace, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return Response(content=canonical, media_type="application/json")


def _format_cost(value: Any) -> str:
    return f"{value:.6f}"


def _group_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group per-lane candidate rows into Candidate objects, order preserved."""
    order: list[str] = []
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_id = str(row["retrieval_item_id"])
        if item_id not in grouped:
            order.append(item_id)
            grouped[item_id] = {
                "item_id": item_id,
                "kind": row["kind"],
                "contributions": [],
                "fused_score": row["fused_score"],
                "fused_rank": row["fused_rank"],
                "rerank_score": row["rerank_score"],
                "rerank_rank": row["rerank_rank"],
                "accepted": row["accepted"],
                "rejection_code": row["rejection_code"],
                "decision_detail": row["decision_detail"],
                "source_span_id": str(row["source_span_id"]),
                "document_version_id": str(row["document_version_id"]),
                "published_at": row["published_at"].isoformat(),
            }
        grouped[item_id]["contributions"].append(
            {
                "lane": row["lane"],
                "variant_index": row["variant_index"],
                "lane_rank": row["lane_rank"],
                "raw_score": row["raw_score"],
                "normalized_score": row["normalized_score"],
                "rrf_contribution": row["rrf_contribution"],
                "timing_ms": row["timing_ms"],
            }
        )
    for candidate in grouped.values():
        candidate["contributions"].sort(
            key=lambda c: (
                _LANE_ORDER.index(c["lane"]) if c["lane"] in _LANE_ORDER else 99,
                c["variant_index"],
            )
        )
    return [grouped[item_id] for item_id in order]


def _sse_stream(ctx: TenantContext, run_id: str, last_event_id: int) -> Iterator[str]:
    """Yield persisted events (seq > last_event_id) as text/event-stream.

    Events are already committed when this generator runs (they were written in
    the create transaction), so nothing uncommitted is ever emitted. A leading
    heartbeat comment gives the client immediate liveness.
    """
    yield _HEARTBEAT
    with tenant_connection(ctx, snapshot_read=True) as conn:
        rows = conn.execute(
            "SELECT seq, event_type, payload, created_at FROM retrieval_events"
            " WHERE run_id = %s AND seq > %s ORDER BY seq",
            (run_id, last_event_id),
        ).fetchall()
    for row in rows:
        body = json.dumps(
            _event_body(row, run_id), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        yield f"id: {int(row['seq'])}\nevent: {row['event_type']}\ndata: {body}\n\n"


@router.get("/retrieval-runs/{run_id}/events")
def stream_retrieval_run_events(
    run_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
) -> StreamingResponse:
    with tenant_connection(ctx) as conn:
        run = conn.execute("SELECT id FROM retrieval_runs WHERE id = %s", (str(run_id),)).fetchone()
    if run is None:
        raise api_error(404, "NOT_FOUND", "Retrieval run not found.")
    return StreamingResponse(
        _sse_stream(ctx, str(run_id), last_event_id or 0),
        media_type="text/event-stream",
    )


@router.post("/retrieval-runs/{run_id}/feedback", status_code=201)
def create_retrieval_feedback(
    run_id: uuid.UUID,
    body: EvidenceFeedback,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> Response:
    if body.label not in _FEEDBACK_LABELS:
        raise api_error(422, "INVALID_LABEL", "Unknown feedback label.")
    with tenant_connection(ctx) as conn:
        replay = _idempotent_replay(conn, ctx, "createRetrievalFeedback", idempotency_key)
        if replay is not None:
            return Response(status_code=201)
        run = conn.execute("SELECT id FROM retrieval_runs WHERE id = %s", (str(run_id),)).fetchone()
        if run is None:
            raise api_error(404, "NOT_FOUND", "Retrieval run not found.")
        conn.execute(
            "INSERT INTO retrieval_feedback ("
            " id, org_id, run_id, retrieval_item_id, label, actor_user_id,"
            " supersedes_feedback_id, reason"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                ctx.org_id,
                str(run_id),
                str(body.item_id),
                body.label,
                ctx.user_id,
                str(body.supersedes_feedback_id) if body.supersedes_feedback_id else None,
                body.reason,
            ),
        )
        _idempotent_store(conn, ctx, "createRetrievalFeedback", idempotency_key, 201, {})
    return Response(status_code=201)
