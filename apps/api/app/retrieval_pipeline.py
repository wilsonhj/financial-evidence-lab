"""Pinned retrieval pipeline execution with explicit runtime call seams."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg

from app.config import Settings
from app.costs import token_cost_usd
from app.retrieval_queries import GENERATION_MODEL, GENERATION_PROVIDER
from app.retrieval_run_store import _RunWriter
from fel_providers import EmbeddingProvider
from fel_providers.interfaces import StructuredLLMProvider
from fel_retrieval import LANE_ORDER, LaneCall, LaneQuery
from fel_retrieval.fusion import FusionResult
from fel_retrieval.generation import ContextItem, GenerationContractError, StructuredClaimGenerator
from fel_retrieval.lanes import LaneCandidate
from fel_retrieval.verification import MockCitationVerifier, should_abstain, verify_claims


@dataclass(frozen=True)
class PipelineDependencies:
    """Callables selected from the public module when an execution starts."""

    run_writer: Callable[..., _RunWriter]
    resolve_embedding_provider: Callable[[str, str], EmbeddingProvider]
    resolve_generation_provider: Callable[[str, str], StructuredLLMProvider]
    lane_query: Callable[..., LaneQuery]
    lane_call: Callable[[str, LaneQuery, dict[str, int]], LaneCall]
    execute_lanes: Callable[..., dict[str, list[LaneCandidate]]]
    fuse: Callable[..., FusionResult]
    persist_candidates: Callable[..., None]
    load_context_items: Callable[[psycopg.Connection[Any], list[str]], list[ContextItem]]
    context_tokens: Callable[[psycopg.Connection[Any], list[str]], int]
    persist_claims: Callable[..., None]
    settings: Callable[[], Settings]


@dataclass
class _RunUsage:
    """Keep provider usage available even if subsequent persistence fails."""

    cost_usd: Decimal = Decimal("0")
    generation: dict[str, str | None] | None = None


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


def _decision_dict(decision: Any, stamp: str) -> dict[str, Any]:
    body: dict[str, Any] = decision.to_dict()
    body["occurred_at"] = stamp
    return body


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
    deps: PipelineDependencies,
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
    writer = deps.run_writer(conn, run_id=run_id, org_id=org_id)
    embedder = deps.resolve_embedding_provider(embedding_provider, embedding_model)
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
    lane_query = deps.lane_query(plan, embedder=embedder, effective_as_of=effective_as_of)
    for lane in lanes:
        writer.emit("lane_started", {"lane": lane})
    # Fixed-order timings dict, pre-populated so concurrent writes only touch
    # existing keys. execute_lanes fails closed (LaneExecutionError) on any lane.
    lane_timings: dict[str, int] = {lane: 0 for lane in lanes}
    lane_results = deps.execute_lanes(
        [(lane, deps.lane_call(lane, lane_query, lane_timings)) for lane in lanes]
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
    fusion = deps.fuse(lane_results, fused_top_k=budgets["fused_top_k"])
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

    deps.persist_candidates(
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
    context = deps.load_context_items(conn, accepted)
    generator = StructuredClaimGenerator(
        deps.resolve_generation_provider(GENERATION_PROVIDER, GENERATION_MODEL)
    )
    generation_rejection_code: str | None = None
    try:
        generation = generator.generate(plan["variants"][0], context, as_of=plan["effective_as_of"])
    except GenerationContractError as exc:
        # The provider already performed the generation: retain its usage and
        # the selected evidence even though none of its claims can be admitted.
        # Missing usage denotes a failure outside that completed-call seam.
        if exc.usage is None:
            raise
        generation = exc.usage
        generation_rejection_code = exc.code
    # Capture reported usage before verification or database writes can fail.
    usage.cost_usd = token_cost_usd(
        deps.settings(),
        input_tokens=generation.input_tokens,
        output_tokens=generation.output_tokens,
    )
    generation_audit: dict[str, str | None] = {
        "provider": generation.provider,
        "model": generation.model,
        "response_id": generation.response_id,
        "estimated_cost_usd": str(generation.estimated_cost_usd),
    }
    usage.generation = generation_audit
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
    deps.persist_claims(conn, run_id=run_id, org_id=org_id, claims=claims)
    verifying_ms = int((time.monotonic() - t0) * 1000)

    context_tokens = deps.context_tokens(conn, accepted)
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
    cost_usd = usage.cost_usd
    # Missing supporting evidence yields abstention; a contradicted claim is
    # preserved and displayed (the run still succeeds).
    if should_abstain(claims):
        abstention: dict[str, Any] = {"reason": "insufficient_evidence"}
        if generation_rejection_code is not None:
            abstention = {
                "reason": "generation_contract_invalid",
                "code": generation_rejection_code,
            }
        elif generation.refused:
            abstention = {"reason": "provider_refused"}
        elif generation.abstained:
            # The model's free-form reason may contain source/model text. Only
            # the typed disposition belongs in the persisted trace event.
            abstention = {"reason": "model_abstained"}
        abstention["generation"] = generation_audit
        writer.emit("run_abstained", abstention)
        writer.finish_abstained(budget_usage=budget_usage, timings_ms=timings_ms, cost_usd=cost_usd)
    else:
        writer.emit("run_completed", {"status": "succeeded", "generation": generation_audit})
        writer.finish_succeeded(budget_usage=budget_usage, timings_ms=timings_ms, cost_usd=cost_usd)
    return budget_usage, cost_usd
