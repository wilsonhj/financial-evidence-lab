"""Complete bounded retrieval traces and immutable history pages."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, cast

import psycopg
from fastapi import Response

from app.auth import TenantContext
from app.errors import api_error
from app.pagination import Order, page_headers, read_page, scope
from fel_retrieval import LANE_ORDER

TenantConnection = Callable[..., AbstractContextManager[psycopg.Connection[dict[str, Any]]]]


@dataclass(frozen=True)
class TraceReadDependencies:
    """Current facade callables used for one snapshot-consistent trace read."""

    tenant_connection: TenantConnection
    trace_rows: Callable[..., list[dict[str, Any]]]
    event_rows: Callable[[psycopg.Connection[dict[str, Any]], str, int, int], list[dict[str, Any]]]
    group_candidates: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


EVENT_SCHEMA_VERSION = "retrieval-event/v1"

MAX_TRACE_BYTES = 16 * 1024 * 1024

MAX_EVENT_BYTES = 256 * 1024


def _event_body(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "run_id": run_id,
        "seq": int(row["seq"]),
        "type": row["event_type"],
        "occurred_at": row["created_at"].isoformat(),
        "payload": row["payload"],
    }


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


def get_query(
    query_id: uuid.UUID,
    response: Response,
    ctx: TenantContext,
    limit: int | None = None,
    cursor: str | None = None,
    order: Order | None = None,
    *,
    tenant_connection: TenantConnection,
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


def get_retrieval_run(
    run_id: uuid.UUID, ctx: TenantContext, *, deps: TraceReadDependencies
) -> Response:
    """Return the immutable trace, serialized byte-stably (same bytes each read)."""
    with deps.tenant_connection(ctx, snapshot_read=True) as conn:
        budget = [0]
        run_rows = deps.trace_rows(
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
            batch = deps.event_rows(conn, str(run_id), after, high_water)
            if not batch:
                break
            for row in batch:
                budget[0] += len(_event_json(row, str(run_id)).encode())
                if budget[0] > MAX_TRACE_BYTES:
                    raise _trace_too_large("serialized_bytes", MAX_TRACE_BYTES)
                event_rows.append(row)
            after = batch[-1]["seq"]
        _check_candidate_counts(conn, str(run_id))
        candidate_rows = deps.trace_rows(
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
        claim_rows = deps.trace_rows(
            conn,
            "SELECT id, ord, text, status FROM claims WHERE run_id = %s ORDER BY ord",
            (str(run_id),),
            1000,
            "claims",
            budget,
        )
        _check_citation_count(conn, str(run_id))
        citation_rows = deps.trace_rows(
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
        "candidates": deps.group_candidates(candidate_rows),
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


def get_retrieval_event_history(
    run_id: uuid.UUID,
    response: Response,
    ctx: TenantContext,
    limit: int | None = None,
    cursor: str | None = None,
    order: Order | None = None,
    *,
    tenant_connection: TenantConnection,
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
