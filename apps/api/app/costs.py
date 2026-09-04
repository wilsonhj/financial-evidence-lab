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


def billed_query_cost(cfg: Settings, *, input_tokens: int, output_tokens: int) -> Decimal:
    """Metered cost for one research query, never above the spec 18.2 ceiling.

    ``token_cost_usd`` is the honest provider bill; this is what we persist as
    usage. Generation has already run by the time we know the token count, so
    the cap cannot un-spend tokens — it stops the overage from accumulating
    toward daily/monthly hard limits and from being recorded as billed spend.
    """
    actual = token_cost_usd(cfg, input_tokens=input_tokens, output_tokens=output_tokens)
    ceiling = cfg.research_query_cost_usd
    return actual if actual <= ceiling else ceiling


def record_usage(
    conn: psycopg.Connection[Any], ctx: TenantContext, kind: str, cost_usd: Decimal
) -> None:
    conn.execute(
        "INSERT INTO usage_events (org_id, user_id, kind, cost_usd) VALUES (%s, %s, %s, %s)",
        (ctx.org_id, ctx.user_id, kind, cost_usd),
    )


def _inflight_reservations(
    conn: psycopg.Connection[Any], ctx: TenantContext, reservation_usd: Decimal
) -> tuple[Decimal, Decimal]:
    """USD reserved by non-terminal retrieval runs (user today, org this month).

    ``usage_events`` is INSERT-only for ``fel_app``, so a ceiling check cannot
    write a hold row and update it later. In-flight runs (inserted in the
    create transaction, still open while the pipeline runs) stand in as the
    hold; concurrent createQuery calls see them once this session takes the
    advisory lock below.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT
              COALESCE(COUNT(*) FILTER (
                WHERE q.created_by = %s AND r.started_at >= date_trunc('day', now())), 0),
              COALESCE(COUNT(*) FILTER (
                WHERE r.started_at >= date_trunc('month', now())), 0)
            FROM retrieval_runs r
            JOIN queries q ON q.id = r.query_id AND q.org_id = r.org_id
            WHERE r.org_id = %s
              AND r.status NOT IN ('succeeded', 'abstained', 'failed', 'cancelled')
            """,
            (ctx.user_id, ctx.org_id),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("aggregate query returned no row")
    return reservation_usd * int(row[0]), reservation_usd * int(row[1])


def _lock_org_spend(conn: psycopg.Connection[Any], org_id: str) -> None:
    """Serialize ceiling checks for one org until this transaction commits.

    Without it, concurrent createQuery requests all read the same snapshot,
    all pass, and all run. The lock is transaction-scoped so a recycled pool
    connection cannot leak it.
    """
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s), 191)", (org_id,))


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
    _lock_org_spend(conn, ctx.org_id)
    user_day, org_month = spend_snapshot(conn, ctx)
    reserved_user, reserved_org = _inflight_reservations(conn, ctx, upcoming_cost_usd)
    user_day += reserved_user
    org_month += reserved_org
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
