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
        "INSERT INTO usage_events (org_id, user_id, kind, cost_usd) VALUES (%s, %s, %s, %s)",
        (ctx.org_id, ctx.user_id, kind, cost_usd),
    )


def spend_snapshot(conn: psycopg.Connection[Any], ctx: TenantContext) -> tuple[Decimal, Decimal]:
    """(user spend today, org spend this month).

    Row-factory agnostic by construction: the cursor pins ``tuple_row`` rather
    than inheriting the connection's factory, so this works on both a bare
    ``psycopg.connect()`` and the API's ``dict_row`` pooled connections.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(cost_usd) FILTER (
                WHERE user_id = %s AND created_at >= date_trunc('day', now())), 0),
              COALESCE(SUM(cost_usd) FILTER (
                WHERE created_at >= date_trunc('month', now())), 0)
            FROM usage_events WHERE org_id = %s
            """,
            (ctx.user_id, ctx.org_id),
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
