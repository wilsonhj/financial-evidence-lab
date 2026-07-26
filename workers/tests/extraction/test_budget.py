"""Budget precheck / hard-stop unit tests (M3-101)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_providers.interfaces import StructuredModelResult
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import BudgetExceeded


def _result(**kwargs: object) -> StructuredModelResult:
    base = dict(
        provider="mock",
        model="mock-structured-v1",
        response_id="r1",
        parsed={},
        refused=False,
        refusal=None,
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=Decimal("0"),
        raw={},
    )
    base.update(kwargs)
    return StructuredModelResult(**base)  # type: ignore[arg-type]


def test_call_cap_precheck() -> None:
    budget = RunBudget(max_calls=1)
    budget.calls_used = 1
    with pytest.raises(BudgetExceeded):
        budget.precheck(reserve_output_tokens=10)


def test_output_token_reservation() -> None:
    budget = RunBudget(max_output_tokens=10)
    with pytest.raises(BudgetExceeded):
        budget.precheck(reserve_output_tokens=11)


def test_post_call_cost_hard_stop() -> None:
    budget = RunBudget(max_cost_usd=Decimal("1.00"))
    with pytest.raises(BudgetExceeded):
        budget.record(_result(estimated_cost_usd=Decimal("1.50")))


def test_wall_clock_precheck() -> None:
    budget = RunBudget(max_wall_seconds=0)
    with pytest.raises(BudgetExceeded):
        budget.precheck(reserve_output_tokens=1)
