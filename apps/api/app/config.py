"""Environment-driven settings (mock-first: every external service optional)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

# Bounds for every list endpoint (#191). A list route without a ceiling is an
# unbounded scan waiting for a large tenant. An omitted `limit` uses
# DEFAULT_LIST_LIMIT and fails closed (413 LIST_TOO_LARGE) when more rows
# exist — silent oldest-first truncation is an evidence leak. An explicit
# `limit` (max MAX_LIST_LIMIT) is an opted-in page of the newest rows.
# OpenAPI 0.4.0 does not yet declare `limit`; documenting it is a
# contract-change follow-up.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


@dataclass(frozen=True)
class Settings:
    """Runtime configuration; values come from the environment only."""

    database_url: str | None = field(default_factory=lambda: os.environ.get("FEL_DATABASE_URL"))
    storage_dir: str | None = field(default_factory=lambda: os.environ.get("FEL_STORAGE_DIR"))
    auth_mode: str = field(default_factory=lambda: os.environ.get("FEL_AUTH_MODE", "mock"))
    # Spec section 18.2 default hard limits.
    user_daily_cost_limit_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_USER_DAILY_LIMIT_USD", "25"))
    )
    org_monthly_cost_limit_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_ORG_MONTHLY_LIMIT_USD", "1000"))
    )
    # Soft limits warn; hard limits stop billable work (never silent downgrade).
    user_daily_soft_limit_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_USER_DAILY_SOFT_USD", "10"))
    )
    org_monthly_soft_limit_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_ORG_MONTHLY_SOFT_USD", "500"))
    )
    # Spec section 18.2: "a standard research query has a USD 0.25 hard cost
    # ceiling". Charged against the ceilings *before* the pipeline runs, so a
    # caller at the limit is stopped rather than discovering it after billing.
    research_query_cost_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_RESEARCH_QUERY_COST_USD", "0.25"))
    )
    # Placeholder token pricing used to convert reported provider usage into a
    # metered cost. The pinned providers are deterministic mocks today; a live
    # provider factory (packages/providers) will carry real per-model rates.
    cost_per_1k_input_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_COST_PER_1K_INPUT_USD", "0.005"))
    )
    cost_per_1k_output_usd: Decimal = field(
        default_factory=lambda: Decimal(os.environ.get("FEL_COST_PER_1K_OUTPUT_USD", "0.015"))
    )
    # In-process rate limiting (#191). 0 qps disables the limiter entirely.
    rate_limit_qps: float = field(
        default_factory=lambda: float(os.environ.get("FEL_RATE_LIMIT_QPS", "5"))
    )
    rate_limit_burst: float = field(
        default_factory=lambda: float(os.environ.get("FEL_RATE_LIMIT_BURST", "20"))
    )
    # Bounded reader assembly (#191): a single reader response never loads an
    # unbounded number of spans/facts into memory.
    reader_max_spans: int = field(
        default_factory=lambda: int(os.environ.get("FEL_READER_MAX_SPANS", "5000"))
    )
    reader_max_facts: int = field(
        default_factory=lambda: int(os.environ.get("FEL_READER_MAX_FACTS", "5000"))
    )
    reader_max_sections: int = field(
        default_factory=lambda: int(os.environ.get("FEL_READER_MAX_SECTIONS", "5000"))
    )
    reader_max_siblings: int = field(
        default_factory=lambda: int(os.environ.get("FEL_READER_MAX_SIBLINGS", "200"))
    )
    # Connection pool sizing (#191).
    db_pool_min: int = field(default_factory=lambda: int(os.environ.get("FEL_DB_POOL_MIN", "1")))
    db_pool_max: int = field(default_factory=lambda: int(os.environ.get("FEL_DB_POOL_MAX", "10")))


def settings() -> Settings:
    return Settings()
