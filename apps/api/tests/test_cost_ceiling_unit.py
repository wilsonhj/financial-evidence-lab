"""Spec 18.2: a standard research query has a USD 0.25 hard cost ceiling.

No database: this is pure Decimal arithmetic over Settings."""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.costs import billed_query_cost, token_cost_usd


def _cfg(**overrides: object) -> Settings:
    values = dict(
        database_url=None,
        auth_mode="mock",
        research_query_cost_usd=Decimal("0.25"),
        cost_per_1k_input_usd=Decimal("0.005"),
        cost_per_1k_output_usd=Decimal("0.015"),
    )
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_actual_token_cost_is_capped_at_the_per_query_ceiling() -> None:
    cfg = _cfg()
    # 1e9 input tokens at $0.005/1k is $5_000, well above $0.25.
    actual = token_cost_usd(cfg, input_tokens=1_000_000_000, output_tokens=0)
    assert actual > cfg.research_query_cost_usd
    assert billed_query_cost(cfg, input_tokens=1_000_000_000, output_tokens=0) == Decimal("0.25")


def test_sub_ceiling_usage_is_metered_exactly() -> None:
    cfg = _cfg()
    billed = billed_query_cost(cfg, input_tokens=1000, output_tokens=0)
    assert billed == token_cost_usd(cfg, input_tokens=1000, output_tokens=0)
    assert billed < cfg.research_query_cost_usd
