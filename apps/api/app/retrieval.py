"""Retrieval routes and runtime patch boundaries (M2-015 / T0206, ADR-0006).

Admission, metering/failure control and lazy SSE replay stay together here.
Storage, pinned execution and complete bounded reads have explicit helper modules.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Annotated, Any, cast

import psycopg
from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse

from app.auth import TenantContext
from app.config import settings
from app.costs import (
    enforce_ceilings,
    lock_query_budget,
    record_usage,
)
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from app.pagination import Order
from app.ratelimit import rate_limit
from app.retrieval_pipeline import PipelineDependencies, _lane_query, _RunUsage
from app.retrieval_pipeline import _decision_dict as _decision_dict
from app.retrieval_pipeline import _execute_pipeline as _execute_pipeline_impl
from app.retrieval_pipeline import _parse_iso as _parse_iso
from app.retrieval_queries import _FEEDBACK_LABELS as _FEEDBACK_LABELS
from app.retrieval_queries import GENERATION_MODEL as GENERATION_MODEL
from app.retrieval_queries import GENERATION_PROVIDER as GENERATION_PROVIDER
from app.retrieval_queries import PLANNER_VERSION as PLANNER_VERSION
from app.retrieval_queries import (
    CreateQuery,
    EvidenceFeedback,
    _accepted_body,
    _idempotent_replay,
    _idempotent_store,
    _insert_query,
    _insert_run,
    _resolve_index,
)
from app.retrieval_queries import create_retrieval_feedback as _create_retrieval_feedback_impl
from app.retrieval_reads import EVENT_SCHEMA_VERSION as EVENT_SCHEMA_VERSION
from app.retrieval_reads import MAX_EVENT_BYTES as MAX_EVENT_BYTES
from app.retrieval_reads import MAX_TRACE_BYTES as MAX_TRACE_BYTES
from app.retrieval_reads import (
    TraceReadDependencies,
    _event_json,
    _event_rows,
    _group_candidates,
    _trace_rows,
)
from app.retrieval_reads import _check_candidate_counts as _check_candidate_counts
from app.retrieval_reads import _check_citation_count as _check_citation_count
from app.retrieval_reads import _event_body as _event_body
from app.retrieval_reads import _format_cost as _format_cost
from app.retrieval_reads import _group_claims as _group_claims
from app.retrieval_reads import _trace_too_large as _trace_too_large
from app.retrieval_reads import get_query as _get_query_impl
from app.retrieval_reads import get_retrieval_event_history as _get_retrieval_event_history_impl
from app.retrieval_reads import get_retrieval_run as _get_retrieval_run_impl
from app.retrieval_run_store import (
    _context_tokens,
    _load_context_items,
    _persist_candidates,
    _persist_claims,
    _RunWriter,
)
from app.retrieval_run_store import _numeric_from_fact_row as _numeric_from_fact_row
from fel_providers import EmbeddingProvider, MockEmbeddingProvider
from fel_providers.interfaces import StructuredLLMProvider
from fel_providers.mocks import MockStructuredLLMProvider
from fel_retrieval import LANE_ORDER as LANE_ORDER
from fel_retrieval import (
    LaneCall,
    LaneExecutionError,
    LaneQuery,
    PlannerValidationError,
    QueryRequest,
    dense_lane,
    execute_lanes,
    facts_lane,
    fuse,
    lexical_lane,
    plan_query,
    tables_lane,
)
from fel_retrieval.generation import ContextItem as ContextItem
from fel_retrieval.generation import GeneratedClaim as GeneratedClaim
from fel_retrieval.generation import GenerationContractError as GenerationContractError
from fel_retrieval.generation import NumericTuple as NumericTuple
from fel_retrieval.generation import StructuredClaimGenerator as StructuredClaimGenerator
from fel_retrieval.lanes import LaneCandidate
from fel_retrieval.verification import CitationIntegrityError
from fel_retrieval.verification import MockCitationVerifier as MockCitationVerifier
from fel_retrieval.verification import should_abstain as should_abstain
from fel_retrieval.verification import verify_claims as verify_claims

router = APIRouter(prefix="/v1", tags=["retrieval"])


# Lanes are executed and emitted in the shared fusion order (``LANE_ORDER``) so
# a trace is deterministic.
_LANE_FUNCS: dict[str, Callable[[Any, LaneQuery], list[LaneCandidate]]] = {
    "dense": dense_lane,
    "lexical": lexical_lane,
    "facts": facts_lane,
    "tables": tables_lane,
}

# SSE keep-alive comment. Emitted at stream open (and, for a still-open run,
# between polls) so a client sees liveness within the contract's 15-30s window.
_HEARTBEAT = ": keep-alive\n\n"

# Statement-timeout applied to every retrieval connection (tenant writes and the
# per-lane corpus reads) so a pathological query can never wedge a request.
_STATEMENT_TIMEOUT = "15s"


class UnsupportedEmbeddingProvider(RuntimeError):
    """The pinned embedding provider has no wired implementation.

    Only the deterministic mock exists today; any other pin fails closed here so
    a run records a typed failure rather than silently using the wrong embedder.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(f"embedding provider {provider!r} (model {model!r}) is not available")
        self.provider = provider
        self.model = model


def _resolve_embedding_provider(provider: str, model: str) -> EmbeddingProvider:
    """Resolve the index's pinned embedder. Makes the persisted pin load-bearing.

    ``('mock', ...)`` -> the 512-dim deterministic mock. No live provider is
    wired yet, so every other pin raises ``UnsupportedEmbeddingProvider`` (caught
    by the pipeline-failure path and recorded as a ``failed`` run).
    """
    if provider == "mock":
        return MockEmbeddingProvider(512)
    raise UnsupportedEmbeddingProvider(provider, model)


class UnsupportedGenerationProvider(RuntimeError):
    """The pinned structured-generation provider has no wired implementation.

    Only the deterministic mock exists today; any other pin fails closed so a run
    records a typed failure rather than silently generating with the wrong model.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(f"generation provider {provider!r} (model {model!r}) is not available")
        self.provider = provider
        self.model = model


def _resolve_generation_provider(provider: str, model: str) -> StructuredLLMProvider:
    """Resolve the run's pinned structured-generation provider (mock only today)."""
    if provider == "mock":
        return MockStructuredLLMProvider()
    raise UnsupportedGenerationProvider(provider, model)


# --- Pipeline execution + persistence --------------------------------------


def _lane_call(lane: str, lane_query: LaneQuery, timings: dict[str, int]) -> LaneCall:
    """Bind one lane to its own corpus connection so lanes run concurrently.

    Each lane opens a dedicated read connection (psycopg connections are not
    thread-safe) and records its own wall time into the pre-populated ``timings``
    dict (only existing keys are assigned, so no concurrent resize occurs).
    """

    def _call() -> list[LaneCandidate]:
        with _corpus_read_connection() as read_conn:
            started = time.monotonic()
            candidates = _LANE_FUNCS[lane](read_conn, lane_query)
            timings[lane] = int((time.monotonic() - started) * 1000)
            return candidates

    return _call


def _execute_pipeline(
    conn: psycopg.Connection[Any],
    *,
    run_id: str,
    org_id: str,
    plan: dict[str, Any],
    mode: str,
    embedding_provider: str,
    embedding_model: str,
    usage: _RunUsage,
) -> tuple[dict[str, int], Decimal]:
    """Use the current public call seams for one transactional pipeline execution."""
    return _execute_pipeline_impl(
        conn,
        run_id=run_id,
        org_id=org_id,
        plan=plan,
        mode=mode,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        usage=usage,
        deps=PipelineDependencies(
            run_writer=_RunWriter,
            resolve_embedding_provider=_resolve_embedding_provider,
            resolve_generation_provider=_resolve_generation_provider,
            lane_query=_lane_query,
            lane_call=_lane_call,
            execute_lanes=execute_lanes,
            fuse=fuse,
            persist_candidates=_persist_candidates,
            load_context_items=_load_context_items,
            context_tokens=_context_tokens,
            persist_claims=_persist_claims,
            settings=settings,
        ),
    )


def _corpus_read_connection() -> psycopg.Connection[Any]:
    """A tuple-row read connection over the public corpus for lane SQL.

    Corpus/retrieval tables carry no org_id and no RLS (0002/0003), so a
    plain read connection observes exactly what the pinned lanes filter to;
    all org-scoped work stays on the RLS-bound tenant connection.
    """
    url = settings().database_url
    if url is None:
        raise RuntimeError("FEL_DATABASE_URL is not configured")
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("SELECT set_config('statement_timeout', %s, false)", (_STATEMENT_TIMEOUT,))
    return conn


def _failure_envelope(exc: Exception) -> dict[str, str]:
    """Map a pipeline exception to the run's stored error envelope."""
    if isinstance(exc, UnsupportedEmbeddingProvider):
        return {"code": "EMBEDDING_PROVIDER_UNAVAILABLE", "message": str(exc)}
    if isinstance(exc, LaneExecutionError):
        return {"code": "LANE_EXECUTION_FAILED", "message": str(exc)}
    if isinstance(exc, CitationIntegrityError):
        return {"code": exc.code, "message": str(exc)}
    return {"code": "PIPELINE_FAILED", "message": str(exc)}


def _run_pipeline_or_fail(
    ctx: TenantContext,
    *,
    run_id: str,
    plan: dict[str, Any],
    mode: str,
    embedding_provider: str,
    embedding_model: str,
    usage_kind: str,
) -> None:
    """Execute the pipeline for an already-persisted run, recording durable failure.

    The query/run were committed by the caller; the pipeline runs here in its own
    tenant transaction. A pipeline exception rolls that transaction back (no
    partial trace) and is then recorded as a terminal ``failed`` run in a fresh
    transaction, so a failure is always durably observable.

    The terminal trace and usage event commit together. If either write fails,
    both roll back and the fresh failure transaction records any provider spend
    already reported. If the database cannot persist that either, the queued
    run and its admission reservation remain, so the budget fails closed.
    """
    usage = _RunUsage()

    try:
        with tenant_connection(ctx) as conn:
            conn.execute("SELECT set_config('statement_timeout', %s, true)", (_STATEMENT_TIMEOUT,))
            _, cost_usd = _execute_pipeline(
                conn,
                run_id=run_id,
                org_id=ctx.org_id,
                plan=plan,
                mode=mode,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                usage=usage,
            )
            record_usage(conn, ctx, usage_kind, cost_usd)
    except Exception as exc:
        _record_run_failure(
            ctx,
            run_id=run_id,
            exc=exc,
            usage_kind=usage_kind,
            cost_usd=usage.cost_usd,
            generation=usage.generation,
        )


def _record_run_failure(
    ctx: TenantContext,
    *,
    run_id: str,
    exc: Exception,
    usage_kind: str,
    cost_usd: Decimal,
    generation: dict[str, str | None] | None,
) -> None:
    """Append ``run_failed`` and move the run to ``failed`` in a fresh transaction."""
    error = _failure_envelope(exc)
    with tenant_connection(ctx) as conn:
        conn.execute("SELECT set_config('statement_timeout', %s, true)", (_STATEMENT_TIMEOUT,))
        _RunWriter(conn, run_id=run_id, org_id=ctx.org_id).fail(
            error, cost_usd=cost_usd, generation=generation
        )
        if cost_usd > 0:
            record_usage(conn, ctx, usage_kind, cost_usd)


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
        lock_query_budget(conn, ctx)
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
        lock_query_budget(conn, ctx)
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
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    """Return the complete immutable query snapshot and run history."""
    return _get_query_impl(
        query_id, response, ctx, limit, cursor, order, tenant_connection=tenant_connection
    )


@router.get("/retrieval-runs/{run_id}")
def get_retrieval_run(
    run_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> Response:
    """Return the immutable trace, serialized byte-stably (same bytes each read)."""
    return _get_retrieval_run_impl(
        run_id,
        ctx,
        deps=TraceReadDependencies(
            tenant_connection=tenant_connection,
            trace_rows=_trace_rows,
            event_rows=_event_rows,
            group_candidates=_group_candidates,
        ),
    )


def _sse_stream(
    ctx: TenantContext,
    run_id: str,
    last_event_id: int,
    initial: tuple[int, list[dict[str, Any]]] | None = None,
) -> Iterator[str]:
    """Replay all rows through captured high water, closing DB before every yield."""
    if initial is None:
        with tenant_connection(ctx, snapshot_read=True) as conn:
            high_row = conn.execute(
                "SELECT coalesce(max(seq),0) AS seq FROM retrieval_events" " WHERE run_id = %s",
                (run_id,),
            ).fetchone()
            high_row = cast(dict[str, Any], high_row)
            high = high_row["seq"]
            rows = _event_rows(conn, run_id, last_event_id, high)
    else:
        high, rows = initial
    yield _HEARTBEAT
    heartbeat = time.monotonic()
    after = last_event_id
    while rows:
        for row in rows:
            if time.monotonic() - heartbeat >= 15:
                yield _HEARTBEAT
                heartbeat = time.monotonic()
            body = _event_json(row, run_id)
            yield f"id: {int(row['seq'])}\nevent: {row['event_type']}\ndata: {body}\n\n"
            after = row["seq"]
        if after >= high:
            break
        with tenant_connection(ctx, snapshot_read=True) as conn:
            rows = _event_rows(conn, run_id, after, high)


@router.get("/retrieval-runs/{run_id}/events")
def stream_retrieval_run_events(
    run_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
) -> StreamingResponse:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        run = conn.execute("SELECT id FROM retrieval_runs WHERE id = %s", (str(run_id),)).fetchone()
        if run is None:
            raise api_error(404, "NOT_FOUND", "Retrieval run not found.")
        high_row = conn.execute(
            "SELECT coalesce(max(seq),0) AS seq FROM retrieval_events" " WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        high_row = cast(dict[str, Any], high_row)
        high = high_row["seq"]
        first = _event_rows(conn, str(run_id), last_event_id or 0, high)
    return StreamingResponse(
        _sse_stream(ctx, str(run_id), last_event_id or 0, (high, first)),
        media_type="text/event-stream",
    )


@router.get("/retrieval-runs/{run_id}/event-history")
def get_retrieval_event_history(
    run_id: uuid.UUID,
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    return _get_retrieval_event_history_impl(
        run_id, response, ctx, limit, cursor, order, tenant_connection=tenant_connection
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
    return _create_retrieval_feedback_impl(
        run_id, body, ctx, idempotency_key, tenant_connection=tenant_connection
    )
