"""The six retrieval endpoints and their request models (openapi v0.3.0).

Each write endpoint replays an ``Idempotency-Key`` before doing anything
billable, charges the spec 18.2 ceiling *before* the pipeline runs, commits the
query/run, and only then executes the pipeline in its own transaction so a
pipeline failure is recorded as a durable ``failed`` run rather than lost with
the request. Reads serialize the immutable trace byte-stably.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.auth import TenantContext
from app.config import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, settings
from app.costs import enforce_ceilings
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from app.ratelimit import rate_limit
from app.retrieval.idempotency import _idempotent_replay, _idempotent_store
from app.retrieval.persistence import _insert_query, _insert_run, _resolve_index
from app.retrieval.pipeline import _run_pipeline_or_fail
from app.retrieval.serializers import (
    _accepted_body,
    _event_body,
    _format_cost,
    _group_candidates,
    _group_claims,
)
from app.retrieval.sse import _sse_stream
from fel_retrieval import PlannerValidationError, QueryRequest, plan_query

router = APIRouter(prefix="/v1", tags=["retrieval"])


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

# --- Cost controls ----------------------------------------------------------
# Spec 18.2 gives a standard research query a USD 0.25 hard cost ceiling. That
# figure is charged against the user/org ceilings *before* the pipeline runs:
# a caller already at their limit is refused rather than billed and then told.
# The hard stop keeps the code costs.py already raises and tests
# (COST_LIMIT_EXCEEDED / 402) rather than inventing a second name for one
# condition; see the costs module docstring for why 402 and not 429.
_COST_WARNING_HEADER = "X-FEL-Cost-Warning"


def _enforce_query_ceilings(conn: psycopg.Connection[Any], ctx: TenantContext) -> str | None:
    cfg = settings()
    return enforce_ceilings(conn, ctx, cfg, cfg.research_query_cost_usd)


# --- Endpoints --------------------------------------------------------------
@router.post(
    "/workspaces/{workspace_id}/queries",
    status_code=202,
    dependencies=[Depends(rate_limit("createQuery"))],
)
def create_query(
    workspace_id: uuid.UUID,
    body: CreateQuery,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    response: Response,
) -> dict[str, Any]:
    with tenant_connection(ctx) as conn:
        replay = _idempotent_replay(conn, ctx, "createQuery", idempotency_key)
        if replay is not None:
            # A replay bills nothing and is not a new billable run, so it is
            # neither ceiling-checked nor metered.
            return replay

        cost_warning = _enforce_query_ceilings(conn, ctx)

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

        index = _resolve_index(
            conn,
            index_version_id=body.index_version_id,
            corpus_version_id=body.corpus_version_id,
        )
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
            question=body.question,
            parent_query_id=body.parent_query_id,
            index=index,
            plan_dict=plan_dict,
            effective_as_of=effective_as_of,
        )
        run_id = _insert_run(
            conn, ctx, query_id=query_id, index=index, mode="execute", parent_run_id=None
        )
        accepted = _accepted_body(query_id, run_id)
        _idempotent_store(conn, ctx, "createQuery", idempotency_key, 202, accepted)

    # Query + run are committed (status queued); execute the pipeline in its own
    # transaction so a pipeline failure is recorded as a durable ``failed`` run.
    _run_pipeline_or_fail(
        ctx,
        run_id=run_id,
        plan=plan_dict,
        mode="execute",
        embedding_provider=index["embedding_provider"],
        embedding_model=index["embedding_model"],
        usage_kind="research_query",
    )
    if cost_warning is not None:
        response.headers[_COST_WARNING_HEADER] = cost_warning
    response.status_code = 202
    return accepted


@router.post(
    "/queries/{query_id}/reruns",
    status_code=202,
    dependencies=[Depends(rate_limit("createQueryRerun"))],
)
def create_query_rerun(
    query_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    response: Response,
) -> dict[str, Any]:
    with tenant_connection(ctx) as conn:
        replay = _idempotent_replay(conn, ctx, "createQueryRerun", idempotency_key)
        if replay is not None:
            return replay

        # A rerun re-executes the whole pipeline, so it is billable exactly like
        # a new query and carries the same ceiling.
        cost_warning = _enforce_query_ceilings(conn, ctx)

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
        accepted = _accepted_body(str(query_id), run_id)
        _idempotent_store(conn, ctx, "createQueryRerun", idempotency_key, 202, accepted)
        plan_dict = dict(query["plan"])
        embedding_provider = index["embedding_provider"]
        embedding_model = index["embedding_model"]

    _run_pipeline_or_fail(
        ctx,
        run_id=run_id,
        plan=plan_dict,
        mode="rerun",
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        usage_kind="research_query_rerun",
    )
    if cost_warning is not None:
        response.headers[_COST_WARNING_HEADER] = cost_warning
    response.status_code = 202
    return accepted


@router.get("/queries/{query_id}")
def get_query(
    query_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:
    """Return the immutable query snapshot with its run history.

    ``limit`` bounds the embedded run list (#191): a heavily rerun query
    otherwise grows this response without limit.
    """
    with tenant_connection(ctx, snapshot_read=True) as conn:
        query = conn.execute(
            "SELECT id, parent_query_id, question, plan, created_at FROM queries WHERE id = %s",
            (str(query_id),),
        ).fetchone()
        if query is None:
            raise api_error(404, "NOT_FOUND", "Query not found.")
        runs = conn.execute(
            "SELECT id, parent_run_id, status, mode, started_at FROM retrieval_runs"
            " WHERE query_id = %s ORDER BY started_at, id::text LIMIT %s",
            (str(query_id), limit),
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
        claim_rows = conn.execute(
            "SELECT id, ord, text, status FROM claims WHERE run_id = %s ORDER BY ord",
            (str(run_id),),
        ).fetchall()
        citation_rows = conn.execute(
            "SELECT claim_id, retrieval_item_id, source_span_id, status, numeric_checks"
            " FROM citations WHERE run_id = %s"
            " ORDER BY claim_id::text, retrieval_item_id::text, source_span_id::text",
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
        "claims": _group_claims(claim_rows, citation_rows),
        "timings_ms": run["timings_ms"],
        "budget_usage": run["budget_usage"],
        "cost_usd": _format_cost(run["cost_usd"]),
        "started_at": run["started_at"].isoformat(),
        "finished_at": run["finished_at"].isoformat() if run["finished_at"] else None,
    }
    canonical = json.dumps(trace, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return Response(content=canonical, media_type="application/json")


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


@router.post(
    "/retrieval-runs/{run_id}/feedback",
    status_code=201,
    dependencies=[Depends(rate_limit("createRetrievalFeedback"))],
)
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
        try:
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
        except (psycopg.errors.RaiseException, psycopg.errors.ForeignKeyViolation) as exc:
            # The DB guard rejects an item that is not a candidate of this run
            # (P0001), and an item that does not exist at all trips the item FK
            # (23503); both are caller errors, not server faults.
            raise api_error(
                422, "INVALID_FEEDBACK_ITEM", "Feedback item must be a candidate of this run."
            ) from exc
        _idempotent_store(conn, ctx, "createRetrievalFeedback", idempotency_key, 201, {})
    return Response(status_code=201)
