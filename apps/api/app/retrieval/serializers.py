"""Row -> contract-shape formatting for the retrieval trace.

Pure functions over already-fetched rows: no database access, no side effects.
Ordering is fixed here (contributions by lane order, citations by id) because
``GET /v1/retrieval-runs/{id}`` promises a byte-stable trace — the same run must
serialize to the same bytes on every read.
"""

from __future__ import annotations

from typing import Any

from fel_retrieval import LANE_ORDER

EVENT_SCHEMA_VERSION = "retrieval-event/v1"


def _accepted_body(query_id: str, run_id: str) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "run_id": run_id,
        "events_url": f"/v1/retrieval-runs/{run_id}/events",
    }


def _decision_dict(decision: Any, stamp: str) -> dict[str, Any]:
    body: dict[str, Any] = decision.to_dict()
    body["occurred_at"] = stamp
    return body


def _event_body(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "run_id": run_id,
        "seq": int(row["seq"]),
        "type": row["event_type"],
        "occurred_at": row["created_at"].isoformat(),
        "payload": row["payload"],
    }


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
