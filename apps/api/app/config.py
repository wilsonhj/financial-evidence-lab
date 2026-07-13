"""Environment-driven settings (mock-first: every external service optional)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Settings:
    """Runtime configuration; values come from the environment only."""

    database_url: str | None = field(default_factory=lambda: os.environ.get("FEL_DATABASE_URL"))
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


def settings() -> Settings:
    return Settings()
