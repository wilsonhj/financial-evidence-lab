"""Usage metering and cost ceilings (spec section 18.2).

Soft limits warn (X-FEL-Cost-Warning header); hard limits refuse new
billable work with COST_LIMIT_EXCEEDED — never a silent downgrade.

The hard stop is 402 Payment Required, not 429: the caller is not being asked
to slow down and retry (that is the rate limiter's 429, with Retry-After), it
has exhausted a spending allowance that only a clock rollover or an
administrator raising the limit will restore. Retrying sooner never helps, so
the status must not invite it.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from app.auth import TenantContext
from app.config import Settings
from app.errors import api_error

# usage_events.cost_usd is numeric(12, 6); every metered cost is quantized to
# that scale before it is written so the stored value is exactly what was
# computed, not a silently rounded one.
_CENTI_MICRO = Decimal("0.000001")


def token_cost_usd(cfg: Settings, *, input_tokens: int, output_tokens: int) -> Decimal:
    """Convert reported provider token usage into a metered USD cost.

    Only generation tokens are priced here. The frozen ``EmbeddingProvider``
    protocol (``packages/providers``) returns vectors and reports no token
    usage, so embedding spend cannot be metered without a contract change;
    when the live provider factory lands with usage on its embedding results,
    this is the one place that has to learn about it.
    """
    cost = (
        Decimal(max(0, input_tokens)) * cfg.cost_per_1k_input_usd
        + Decimal(max(0, output_tokens)) * cfg.cost_per_1k_output_usd
    ) / Decimal(1000)
    return cost.quantize(_CENTI_MICRO, rounding=ROUND_HALF_UP)


def record_usage(
    conn: psycopg.Connection[Any], ctx: TenantContext, kind: str, cost_usd: Decimal
) -> None:
    conn.execute(
        "INSERT INTO usage_events (org_id, user_id, kind, cost_usd, created_at)"
        " VALUES (%s, %s, %s, %s, statement_timestamp())",
        (ctx.org_id, ctx.user_id, kind, cost_usd),
    )


def lock_query_budget(conn: psycopg.Connection[Any], ctx: TenantContext) -> None:
    """Serialize admission only, across API processes, until reservation commit.

    The following spend SELECT gets a fresh READ COMMITTED snapshot after this
    statement finishes waiting. Never hold this lock during provider calls.
    The namespace separates cost admission from other advisory-lock users;
    hash collisions only serialize unrelated organizations.
    """
    conn.execute("SELECT pg_advisory_xact_lock(191, hashtext(%s::uuid::text))", (ctx.org_id,))


def reserve_query_cost(
    conn: psycopg.Connection[Any], ctx: TenantContext, run_id: str, cost_usd: Decimal
) -> None:
    """Record an immutable admission reservation alongside the queued run.

    The existing audit envelope records the actual caller (including a rerun
    by another workspace member) and the configured amount at admission. No
    schema or public run payload changes are needed. Run terminalization and
    metering atomically replace the pending reservation with actual usage.
    """
    conn.execute(
        "INSERT INTO audit_events (org_id, actor_user_id, action, object_type, object_id, payload)"
        " VALUES (%s, %s, 'research_query.reserve', 'retrieval_run', %s, %s::jsonb)",
        (ctx.org_id, ctx.user_id, run_id, json.dumps({"cost_usd": str(cost_usd)})),
    )


def spend_snapshot(conn: psycopg.Connection[Any], ctx: TenantContext) -> tuple[Decimal, Decimal]:
    """User/day and org/month spend, including durable in-flight reservations.

    Read actual and reserved spend in ONE statement: concurrent completion
    must never be missed between two snapshots, or counted twice. Pending
    reservations have no date filter, so a midnight/month rollover cannot
    make unfinished work free. The cursor pins tuple_row for pooled callers.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            WITH actual AS (
                SELECT
                    COALESCE(SUM(cost_usd) FILTER (
                        WHERE user_id = %(user_id)s
                        AND created_at >= date_trunc('day', statement_timestamp())), 0) AS user_day,
                    COALESCE(SUM(cost_usd) FILTER (
                        WHERE created_at >= date_trunc('month', statement_timestamp())
                    ), 0) AS org_month
                FROM usage_events WHERE org_id = %(org_id)s
            ), pending AS (
                SELECT
                    COALESCE(SUM((a.payload->>'cost_usd')::numeric) FILTER (
                        WHERE a.actor_user_id = %(user_id)s), 0) AS user_day,
                    COALESCE(SUM((a.payload->>'cost_usd')::numeric), 0) AS org_month
                FROM audit_events a
                JOIN retrieval_runs r ON r.id::text = a.object_id AND r.org_id = a.org_id
                WHERE a.org_id = %(org_id)s AND a.action = 'research_query.reserve'
                  AND a.object_type = 'retrieval_run' AND r.finished_at IS NULL
            )
            SELECT actual.user_day + pending.user_day, actual.org_month + pending.org_month
            FROM actual CROSS JOIN pending
            """,
            {"user_id": ctx.user_id, "org_id": ctx.org_id},
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("aggregate query returned no row")
    return Decimal(row[0]), Decimal(row[1])


def enforce_ceilings(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    cfg: Settings,
    upcoming_cost_usd: Decimal,
) -> str | None:
    """Returns a soft-limit warning string, or raises on a hard limit."""
    user_day, org_month = spend_snapshot(conn, ctx)
    if user_day + upcoming_cost_usd > cfg.user_daily_cost_limit_usd:
        raise api_error(
            402,
            "COST_LIMIT_EXCEEDED",
            "User daily hard cost limit reached; new billable work is stopped.",
            {"limit_usd": str(cfg.user_daily_cost_limit_usd), "spent_usd": str(user_day)},
        )
    if org_month + upcoming_cost_usd > cfg.org_monthly_cost_limit_usd:
        raise api_error(
            402,
            "COST_LIMIT_EXCEEDED",
            "Organization monthly hard cost limit reached; new billable work is stopped.",
            {"limit_usd": str(cfg.org_monthly_cost_limit_usd), "spent_usd": str(org_month)},
        )
    if user_day + upcoming_cost_usd > cfg.user_daily_soft_limit_usd:
        return "user daily soft limit exceeded"
    if org_month + upcoming_cost_usd > cfg.org_monthly_soft_limit_usd:
        return "organization monthly soft limit exceeded"
    return None
