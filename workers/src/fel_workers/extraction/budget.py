"""Run budget reservation and hard-stop accounting (M3-WF-005/006)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

from fel_providers.interfaces import StructuredModelResult
from fel_workers.extraction.errors import BudgetExceeded


@dataclass
class RunBudget:
    """In-process mirror of ``extraction_runs`` caps/usage (migration 0004)."""

    max_calls: int = 10
    max_input_tokens: int = 100_000
    max_output_tokens: int = 20_000
    max_cost_usd: Decimal = Decimal("2.00")
    max_wall_seconds: int = 600
    calls_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    cost_usd: Decimal = Decimal("0")
    started_monotonic: float = field(default_factory=time.monotonic)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic

    def precheck(self, *, reserve_output_tokens: int) -> None:
        """Refuse the call while everything knowable pre-call still fits."""
        if self.elapsed_seconds() > self.max_wall_seconds:
            raise BudgetExceeded(f"wall clock cap {self.max_wall_seconds}s reached")
        if self.calls_used >= self.max_calls:
            raise BudgetExceeded(f"call cap {self.max_calls} reached")
        if self.output_tokens_used + reserve_output_tokens > self.max_output_tokens:
            raise BudgetExceeded("reserved output tokens would exceed cap")
        if self.input_tokens_used >= self.max_input_tokens:
            raise BudgetExceeded("input-token cap reached")
        if self.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded("cost cap reached")

    def record(self, result: StructuredModelResult) -> None:
        """Post-call hard stop; a single call may overshoot and terminate."""
        self.calls_used += 1
        self.input_tokens_used += result.input_tokens
        self.output_tokens_used += result.output_tokens
        self.cost_usd += result.estimated_cost_usd
        if self.cost_usd > self.max_cost_usd:
            raise BudgetExceeded("cost cap crossed by completed call; run stops")
        if self.input_tokens_used > self.max_input_tokens:
            raise BudgetExceeded("input-token cap crossed by completed call; run stops")
        if self.output_tokens_used > self.max_output_tokens:
            raise BudgetExceeded("output-token cap crossed by completed call; run stops")
        if self.elapsed_seconds() > self.max_wall_seconds:
            raise BudgetExceeded(f"wall clock cap {self.max_wall_seconds}s reached")


__all__ = ["RunBudget"]
