"""T0008: metering, soft warnings, and hard-stop ceilings."""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from app.auth import TenantContext
from app.config import Settings
from app.costs import enforce_ceilings, record_usage, spend_snapshot
from app.errors import api_error  # noqa: F401  (documents the raised shape)
from tests.conftest import requires_db

pytestmark = requires_db


def _ctx(org: tuple[str, str]) -> TenantContext:
    return TenantContext(org_id=org[0], user_id=org[1], role="editor")


def _cfg() -> Settings:
    return Settings(
        database_url=None,
        auth_mode="mock",
        user_daily_cost_limit_usd=Decimal("25"),
        org_monthly_cost_limit_usd=Decimal("1000"),
        user_daily_soft_limit_usd=Decimal("10"),
        org_monthly_soft_limit_usd=Decimal("500"),
    )


def test_metering_and_ceilings(db_url: str, org_fixture: tuple[str, str]) -> None:
    ctx = _ctx(org_fixture)
    with psycopg.connect(db_url) as conn:
        record_usage(conn, ctx, "research_query", Decimal("0.25"))
        user_day, org_month = spend_snapshot(conn, ctx)
        assert user_day == Decimal("0.25") and org_month == Decimal("0.25")

        assert enforce_ceilings(conn, ctx, _cfg(), Decimal("0.25")) is None

        record_usage(conn, ctx, "extraction_batch", Decimal("11"))
        warning = enforce_ceilings(conn, ctx, _cfg(), Decimal("0.25"))
        assert warning == "user daily soft limit exceeded"

        record_usage(conn, ctx, "forecast_job", Decimal("14"))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            enforce_ceilings(conn, ctx, _cfg(), Decimal("1"))
        assert excinfo.value.status_code == 402
        assert excinfo.value.detail["code"] == "COST_LIMIT_EXCEEDED"
