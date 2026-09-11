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

Generation (M2-020) decomposes the selected context into atomic claims via the
pinned structured provider; verification (M2-021) re-derives every citation edge
from the evidence and persists claims with their edges before the run goes
terminal. When no claim is supported (e.g. the provider refused), the run
abstains — ``verifying -> abstained`` with a terminal ``run_abstained`` event —
otherwise it succeeds (a contradicted claim is preserved and displayed, M2-022).
"""

from __future__ import annotations

import json
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
from app.pagination import Order, page_headers, read_page, scope
from app.ratelimit import rate_limit
from app.retrieval_pipeline import PipelineDependencies, _lane_query, _RunUsage
from app.retrieval_pipeline import _decision_dict as _decision_dict
from app.retrieval_pipeline import _execute_pipeline as _execute_pipeline_impl
from app.retrieval_pipeline import _parse_iso as _parse_iso
from app.retrieval_queries import (
    _FEEDBACK_LABELS,
    CreateQuery,
    EvidenceFeedback,
    _accepted_body,
    _idempotent_replay,
    _idempotent_store,
    _insert_query,
    _insert_run,
    _resolve_index,
)
from app.retrieval_queries import GENERATION_MODEL as GENERATION_MODEL
from app.retrieval_queries import GENERATION_PROVIDER as GENERATION_PROVIDER
from app.retrieval_queries import PLANNER_VERSION as PLANNER_VERSION
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
from fel_retrieval import (
    LANE_ORDER,
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

EVENT_SCHEMA_VERSION = "retrieval-event/v1"

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


# --- Idempotency ------------------------------------------------------------


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


# --- Query / run resolution -------------------------------------------------


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
    with tenant_connection(ctx, snapshot_read=True) as conn:
        query = conn.execute(
            "SELECT id, parent_query_id, question, plan, created_at FROM queries WHERE id = %s",
            (str(query_id),),
        ).fetchone()
        if query is None:
            raise api_error(404, "NOT_FOUND", "Query not found.")
        runs, page = read_page(
            conn,
            query="SELECT id, parent_run_id, status, mode, started_at FROM retrieval_runs"
            " WHERE query_id = %s AND org_id = %s",
            params=(query_id, ctx.org_id),
            keys=("started_at", "id"),
            request_scope=scope("runs", ctx.org_id, query_id),
            limit=limit,
            token=cursor,
            order=order,
        )
    page_headers(response, page)
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


MAX_TRACE_BYTES = 16 * 1024 * 1024
MAX_EVENT_BYTES = 256 * 1024


def _trace_too_large(kind: str, limit: int) -> Exception:
    return api_error(
        413,
        "TRACE_TOO_LARGE",
        "Retrieval evidence exceeds a resource limit.",
        {"resource": "retrieval_trace", "limit_kind": kind, "limit": limit},
    )


def _trace_rows(
    conn: psycopg.Connection[dict[str, Any]],
    query: str,
    params: tuple[Any, ...],
    cap: int,
    kind: str,
    budget: list[int],
) -> list[dict[str, Any]]:
    """Probe bounded count/serialized size before transferring any large payload."""
    from psycopg import sql

    bounded = sql.SQL(query) + sql.SQL(" LIMIT %s")
    probe = conn.execute(
        sql.SQL(
            "SELECT count(*) AS n, coalesce(sum(octet_length(to_jsonb(t)::text)),0) AS bytes"
            " FROM ({}) t"
        ).format(bounded),
        (*params, cap + 1),
    ).fetchone()
    probe = cast(dict[str, Any], probe)
    if probe["n"] > cap:
        raise _trace_too_large(kind, cap)
    budget[0] += int(probe["bytes"])
    if budget[0] > MAX_TRACE_BYTES:
        raise _trace_too_large("serialized_bytes", MAX_TRACE_BYTES)
    return conn.execute(bounded, (*params, cap)).fetchall()


def _check_candidate_counts(conn: psycopg.Connection[dict[str, Any]], run_id: str) -> None:
    rows = conn.execute(
        "SELECT retrieval_item_id FROM retrieval_candidates WHERE run_id = %s LIMIT 32001",
        (run_id,),
    ).fetchall()
    if len(rows) > 32000:
        raise _trace_too_large("candidate_contributions", 32000)
    if len({row["retrieval_item_id"] for row in rows}) > 2000:
        raise _trace_too_large("candidates", 2000)


def _check_citation_count(conn: psycopg.Connection[dict[str, Any]], run_id: str) -> None:
    rows = conn.execute(
        "SELECT id FROM citations WHERE run_id = %s LIMIT 16001", (run_id,)
    ).fetchall()
    if len(rows) > 16000:
        raise _trace_too_large("citations", 16000)


def _event_rows(
    conn: psycopg.Connection[dict[str, Any]], run_id: str, after: int, high_water: int
) -> list[dict[str, Any]]:
    # The SQL CASE prevents oversized JSON payloads crossing the DB boundary.
    rows = conn.execute(
        "SELECT seq, event_type, created_at, octet_length(payload::text) AS payload_bytes,"
        " CASE WHEN octet_length(payload::text) <= %s THEN payload ELSE NULL END AS payload"
        " FROM retrieval_events WHERE run_id = %s AND seq > %s AND seq <= %s"
        " ORDER BY seq LIMIT 200",
        (MAX_EVENT_BYTES, run_id, after, high_water),
    ).fetchall()
    for row in rows:
        if row["payload_bytes"] > MAX_EVENT_BYTES:
            raise _trace_too_large("event_bytes", MAX_EVENT_BYTES)
        if len(_event_json(row, run_id).encode()) > MAX_EVENT_BYTES:
            raise _trace_too_large("event_bytes", MAX_EVENT_BYTES)
    return rows


def _event_json(row: dict[str, Any], run_id: str) -> str:
    return json.dumps(
        _event_body(row, run_id), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


@router.get("/retrieval-runs/{run_id}")
def get_retrieval_run(
    run_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> Response:
    """Return the immutable trace, serialized byte-stably (same bytes each read)."""
    with tenant_connection(ctx, snapshot_read=True) as conn:
        budget = [0]
        run_rows = _trace_rows(
            conn,
            "SELECT r.id, r.query_id, r.parent_run_id, r.status, r.config_hash,"
            " r.embedding_provider, r.embedding_model, r.generation_provider,"
            " r.generation_model, r.planner_version, r.budget_usage, r.cost_usd,"
            " r.timings_ms, r.started_at, r.finished_at,"
            " q.plan, q.corpus_version_id, q.index_version_id"
            " FROM retrieval_runs r JOIN queries q ON q.id = r.query_id AND q.org_id = r.org_id"
            " WHERE r.id = %s",
            (str(run_id),),
            1,
            "run",
            budget,
        )
        if not run_rows:
            raise api_error(404, "NOT_FOUND", "Retrieval run not found.")
        run = run_rows[0]
        event_probe = conn.execute(
            "SELECT seq FROM retrieval_events WHERE run_id = %s ORDER BY seq LIMIT 10001",
            (str(run_id),),
        ).fetchall()
        if len(event_probe) > 10000:
            raise _trace_too_large("events", 10000)
        high_water = event_probe[-1]["seq"] if event_probe else 0
        event_rows = []
        after = 0
        while after < high_water:
            batch = _event_rows(conn, str(run_id), after, high_water)
            if not batch:
                break
            for row in batch:
                budget[0] += len(_event_json(row, str(run_id)).encode())
                if budget[0] > MAX_TRACE_BYTES:
                    raise _trace_too_large("serialized_bytes", MAX_TRACE_BYTES)
                event_rows.append(row)
            after = batch[-1]["seq"]
        _check_candidate_counts(conn, str(run_id))
        candidate_rows = _trace_rows(
            conn,
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
            32000,
            "candidate_contributions",
            budget,
        )
        claim_rows = _trace_rows(
            conn,
            "SELECT id, ord, text, status FROM claims WHERE run_id = %s ORDER BY ord",
            (str(run_id),),
            1000,
            "claims",
            budget,
        )
        _check_citation_count(conn, str(run_id))
        citation_rows = _trace_rows(
            conn,
            "SELECT claim_id, retrieval_item_id, source_span_id, status, numeric_checks"
            " FROM citations WHERE run_id = %s"
            " ORDER BY claim_id::text, retrieval_item_id::text, source_span_id::text",
            (str(run_id),),
            16000,
            "citations",
            budget,
        )

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
    if len(canonical.encode()) > MAX_TRACE_BYTES:
        raise _trace_too_large("serialized_bytes", MAX_TRACE_BYTES)
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
                LANE_ORDER.index(c["lane"]) if c["lane"] in LANE_ORDER else 99,
                c["variant_index"],
            )
        )
    return [grouped[item_id] for item_id in order]


def _group_claims(
    claim_rows: list[dict[str, Any]], citation_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Assemble the trace's retrievalClaim list (claims + their citation edges).

    Ordered by claim ``ord`` with citations in a stable id order so the trace is
    byte-stable across reads.
    """
    citations_by_claim: dict[str, list[dict[str, Any]]] = {}
    for row in citation_rows:
        citations_by_claim.setdefault(str(row["claim_id"]), []).append(
            {
                "item_id": str(row["retrieval_item_id"]),
                "source_span_id": str(row["source_span_id"]),
                "status": row["status"],
                "numeric_checks": row["numeric_checks"] or {},
            }
        )
    return [
        {
            "id": str(row["id"]),
            "text": row["text"],
            "status": row["status"],
            "citations": citations_by_claim.get(str(row["id"]), []),
        }
        for row in claim_rows
    ]


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
    with tenant_connection(ctx, snapshot_read=True) as conn:
        run = conn.execute("SELECT id FROM retrieval_runs WHERE id = %s", (run_id,)).fetchone()
        if run is None:
            raise api_error(404, "NOT_FOUND", "Retrieval run not found.")
        rows, page = read_page(
            conn,
            query="SELECT seq, event_type, created_at,"
            " octet_length(payload::text) AS payload_bytes,"
            " CASE WHEN octet_length(payload::text) <= %s THEN payload ELSE NULL END AS payload"
            " FROM retrieval_events WHERE run_id = %s",
            params=(MAX_EVENT_BYTES, run_id),
            keys=("seq",),
            request_scope=scope("events", ctx.org_id, run_id),
            limit=limit,
            token=cursor,
            order=order,
            force_page=True,
        )
        for row in rows:
            if (
                row["payload_bytes"] > MAX_EVENT_BYTES
                or len(_event_json(row, str(run_id)).encode()) > MAX_EVENT_BYTES
            ):
                raise _trace_too_large("event_bytes", MAX_EVENT_BYTES)
    page = cast(dict[str, Any], page)
    page_headers(response, page)
    return {
        "run_id": str(run_id),
        "items": [_event_body(row, str(run_id)) for row in rows],
        "next_cursor": page["next_cursor"],
        "previous_cursor": page["previous_cursor"],
    }


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
