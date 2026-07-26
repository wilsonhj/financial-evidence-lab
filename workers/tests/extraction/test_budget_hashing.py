"""Budget + hashing unit tests (M3-101)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fel_providers.interfaces import StructuredModelResult
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import BudgetExceeded
from fel_workers.extraction.hashing import hash_json, stage_input_hash


def _result(
    *, input_tokens: int = 10, output_tokens: int = 5, cost: str = "0.01"
) -> StructuredModelResult:
    return StructuredModelResult(
        provider="mock",
        model="mock-structured-v1",
        response_id="r1",
        parsed={"ok": True},
        refused=False,
        refusal=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=Decimal(cost),
        raw={},
    )


def test_budget_precheck_call_cap() -> None:
    budget = RunBudget(max_calls=0)
    with pytest.raises(BudgetExceeded):
        budget.precheck(reserve_output_tokens=1)


def test_budget_record_hard_stops_on_cost() -> None:
    budget = RunBudget(max_cost_usd=Decimal("0.05"))
    budget.record(_result(cost="0.04"))
    with pytest.raises(BudgetExceeded):
        budget.record(_result(cost="0.02"))


def test_stage_input_hash_stable() -> None:
    a = stage_input_hash(run_id="r", step_name="normalize", payload={"x": 1}, workflow_version="v1")
    b = stage_input_hash(run_id="r", step_name="normalize", payload={"x": 1}, workflow_version="v1")
    assert (
        a
        == b
        == hash_json(
            {"run_id": "r", "step_name": "normalize", "payload": {"x": 1}, "workflow_version": "v1"}
        )
    )
