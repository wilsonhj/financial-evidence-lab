"""Transactional retrieval run, candidate and claim persistence."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import psycopg

from fel_retrieval.generation import (
    ContextItem,
    GeneratedClaim,
    NumericTuple,
)


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

    def fail(
        self,
        error: dict[str, str],
        *,
        cost_usd: Decimal = Decimal("0"),
        generation: dict[str, str | None] | None = None,
    ) -> None:
        # Append the terminal ``run_failed`` event, then move the run to the
        # terminal ``failed`` status. ``fel_guard_retrieval_run`` allows a
        # transition to ``failed`` from any open status once ``run_failed`` is the
        # latest event; only column-scoped grant fields are written.
        payload: dict[str, Any] = {"error": error}
        if generation is not None:
            payload["generation"] = generation
        self.emit("run_failed", payload)
        self._conn.execute(
            "UPDATE retrieval_runs SET status = 'failed', finished_at = now(),"
            " error = %s::jsonb, cost_usd = %s WHERE id = %s",
            (json.dumps(error), cost_usd, self._run_id),
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
