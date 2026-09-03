"""One run of the pinned lanes -> fusion -> generation -> verification pipeline.

The pipeline executes exactly once per run and persists its whole ordered trace
inside a single tenant transaction, so a run either materialises fully or not at
all. A raised exception rolls that transaction back (no partial trace) and is
then recorded as a terminal ``failed`` run in a fresh transaction, so a failure
is always durably observable.

Lane reads run over the public corpus tables (``documents``/``retrieval_*``
carry no org_id and no RLS by design — see ``0002``/``0003``) on a dedicated
read connection with a tuple row factory, because the lane SQL in
``fel_retrieval`` consumes positional rows. Org isolation is unaffected: every
org-scoped write stays on the RLS-bound tenant connection.

Generation (M2-020) decomposes the selected context into atomic claims via the
pinned structured provider; verification (M2-021) re-derives every citation edge
from the evidence and persists claims with their edges before the run goes
terminal. When no claim is supported the run abstains — ``verifying ->
abstained`` with a terminal ``run_abstained`` event — otherwise it succeeds (a
contradicted claim is preserved and displayed, M2-022).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg

from app.auth import TenantContext
from app.config import settings
from app.costs import record_usage, token_cost_usd
from app.db import corpus_read_connection, tenant_connection
from app.retrieval.persistence import (
    _STATEMENT_TIMEOUT,
    _context_tokens,
    _load_context_items,
    _persist_candidates,
    _persist_claims,
    _record_run_failure,
    _RunWriter,
)
from app.retrieval.providers import (
    _resolve_embedding_provider,
    _resolve_generation_provider,
    generation_pin,
)
from app.retrieval.serializers import _decision_dict
from fel_providers import EmbeddingProvider
from fel_retrieval import (
    LANE_ORDER,
    LaneCall,
    LaneQuery,
    dense_lane,
    execute_lanes,
    facts_lane,
    fuse,
    lexical_lane,
    tables_lane,
)
from fel_retrieval.generation import StructuredClaimGenerator
from fel_retrieval.lanes import LaneCandidate
from fel_retrieval.verification import MockCitationVerifier, should_abstain, verify_claims

# Lanes are executed and emitted in the shared fusion order (``LANE_ORDER``) so
# a trace is deterministic.
_LANE_FUNCS: dict[str, Callable[[Any, LaneQuery], list[LaneCandidate]]] = {
    "dense": dense_lane,
    "lexical": lexical_lane,
    "facts": facts_lane,
    "tables": tables_lane,
}


def _corpus_read_connection() -> AbstractContextManager[psycopg.Connection[Any]]:
    """A pooled tuple-row read connection over the public corpus for lane SQL.

    Thin binding of ``db.corpus_read_connection`` to retrieval's statement
    timeout, so the timeout lives with the rest of the retrieval budget rather
    than in the generic pool module.
    """
    return corpus_read_connection(statement_timeout=_STATEMENT_TIMEOUT)


def _parse_iso(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _lane_query(
    plan: dict[str, Any], *, embedder: EmbeddingProvider, effective_as_of: datetime
) -> LaneQuery:
    filters = plan.get("filters", {})
    forms = filters.get("forms") or None
    periods = filters.get("periods") or None
    query_text = plan["variants"][0]
    query_vector = None
    if "dense" in plan["lanes"]:
        query_vector = embedder.embed([query_text])[0]
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
) -> tuple[dict[str, int], Decimal]:
    """Run lanes -> fusion once and persist the full ordered trace.

    Returns the run's budget usage and its metered cost so the caller can write
    the ``usage_events`` row against the same numbers the trace records.

    All writes are on ``conn`` (tenant/RLS); each lane SELECTs over its own
    dedicated public-corpus connection via ``execute_lanes``. Everything runs
    inside the caller's single transaction, so the run either materialises fully
    succeeded or not at all — a raised ``UnsupportedEmbeddingProvider`` or
    ``LaneExecutionError`` propagates to the failure path, which records a
    ``failed`` run in a fresh transaction.
    """
    writer = _RunWriter(conn, run_id=run_id, org_id=org_id)
    embedder = _resolve_embedding_provider(embedding_provider, embedding_model)
    effective_as_of = _parse_iso(plan["effective_as_of"])
    budgets = plan["budgets"]
    lanes = [lane for lane in LANE_ORDER if lane in plan["lanes"]]

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
    lane_query = _lane_query(plan, embedder=embedder, effective_as_of=effective_as_of)
    for lane in lanes:
        writer.emit("lane_started", {"lane": lane})
    # Fixed-order timings dict, pre-populated so concurrent writes only touch
    # existing keys. execute_lanes fails closed (LaneExecutionError) on any lane.
    lane_timings: dict[str, int] = {lane: 0 for lane in lanes}
    lane_results = execute_lanes(
        [(lane, _lane_call(lane, lane_query, lane_timings)) for lane in lanes]
    )
    for lane in lanes:
        writer.emit(
            "lane_completed",
            {
                "lane": lane,
                "candidates": len(lane_results[lane]),
                "timing_ms": lane_timings[lane],
            },
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
    t0 = time.monotonic()
    context = _load_context_items(conn, accepted)
    generator = StructuredClaimGenerator(_resolve_generation_provider(*generation_pin()))
    generation = generator.generate(plan["variants"][0], context, as_of=plan["effective_as_of"])
    for claim in generation.claims:
        writer.emit(
            "claim_generated",
            {"ord": claim.ord, "citations": len(claim.citations)},
        )
    generating_ms = int((time.monotonic() - t0) * 1000)

    writer.set_status("verifying")
    t0 = time.monotonic()
    # Re-derive every citation edge and support status from the evidence; a
    # dangling/cross-version citation raises CitationIntegrityError (fail closed).
    claims = verify_claims(generation.claims, context, MockCitationVerifier())
    for claim in claims:
        for citation in claim.citations:
            writer.emit(
                "citation_verified",
                {
                    "claim_ord": claim.ord,
                    "item_id": citation.item_id,
                    "status": citation.status,
                    "numeric_checks": citation.numeric_checks,
                },
            )
    _persist_claims(conn, run_id=run_id, org_id=org_id, claims=claims)
    verifying_ms = int((time.monotonic() - t0) * 1000)

    context_tokens = _context_tokens(conn, accepted)
    budget_usage = {
        "context_items": len(accepted),
        "context_tokens": context_tokens,
        "input_tokens": generation.input_tokens,
        "output_tokens": generation.output_tokens,
    }
    timings_ms = {
        "planning": planning_ms,
        "retrieving": retrieving_ms,
        "fusing": fusing_ms,
        "generating": generating_ms,
        "verifying": verifying_ms,
        "total": planning_ms + retrieving_ms + fusing_ms + generating_ms + verifying_ms,
    }
    cost_usd = token_cost_usd(
        settings(),
        input_tokens=generation.input_tokens,
        output_tokens=generation.output_tokens,
    )
    # Missing supporting evidence yields abstention; a contradicted claim is
    # preserved and displayed (the run still succeeds).
    if should_abstain(claims):
        # A provider refusal and an evidence gap both end in zero supported
        # claims, but they are different operational facts: a refusal is a
        # provider-side event to alert on, an evidence gap is a corpus/retrieval
        # quality signal. Collapsing them into one reason makes a refusal spike
        # invisible, so the terminal event names which one happened (#137).
        reason = "provider_refusal" if generation.refused else "insufficient_evidence"
        writer.emit("run_abstained", {"reason": reason})
        writer.finish_abstained(budget_usage=budget_usage, timings_ms=timings_ms, cost_usd=cost_usd)
    else:
        writer.emit("run_completed", {"status": "succeeded"})
        writer.finish_succeeded(budget_usage=budget_usage, timings_ms=timings_ms, cost_usd=cost_usd)
    return budget_usage, cost_usd


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

    A completed run's actual provider usage is metered into ``usage_events``
    (#191) in its own transaction, so metering cannot roll back the trace and a
    metering fault cannot lose the run. A run that failed before generation is
    deliberately not metered: no provider tokens were reported for it, and the
    ceiling check already ran before any billable work started.
    """
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
            )
    except Exception as exc:
        _record_run_failure(ctx, run_id=run_id, exc=exc)
        return
    with tenant_connection(ctx) as conn:
        record_usage(conn, ctx, usage_kind, cost_usd)
