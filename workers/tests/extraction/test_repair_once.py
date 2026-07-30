"""Repair-once / refusal / abstention runner tests (M3-103/104)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from fel_providers.interfaces import (
    StructuredGenerationRequest,
    StructuredModelResult,
)
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import ProviderRefused, SchemaInvalid
from fel_workers.extraction.roles import ROLE_SPECS, Role
from fel_workers.extraction.runner import Abstention, run_model_step


class _ScriptedProvider:
    provider = "mock"
    model = "mock-structured-v1"

    def __init__(self, results: list[StructuredModelResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        del request
        self.calls += 1
        return self._results.pop(0)


def _ok(parsed: dict[str, Any]) -> StructuredModelResult:
    return StructuredModelResult(
        provider="mock",
        model="mock-structured-v1",
        response_id=f"r-{len(parsed)}",
        parsed=parsed,
        refused=False,
        refusal=None,
        input_tokens=3,
        output_tokens=3,
        estimated_cost_usd=Decimal("0"),
        raw={},
    )


def _refuse() -> StructuredModelResult:
    return StructuredModelResult(
        provider="mock",
        model="mock-structured-v1",
        response_id="refuse",
        parsed=None,
        refused=True,
        refusal="nope",
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=Decimal("0"),
        raw={},
    )


def test_exactly_one_repair_then_schema_invalid() -> None:
    bad = _ok({"wrong": True})
    provider = _ScriptedProvider([bad, bad])
    with pytest.raises(SchemaInvalid):
        run_model_step(
            provider=provider,  # type: ignore[arg-type]
            spec=ROLE_SPECS[Role.KPI],
            evidence_blocks=[
                {"source_span_id": "22222222-2222-4222-8222-222222222222", "text": "x"}
            ],
            budget=RunBudget(),
            run_id="00000000-0000-4000-8000-000000000001",
            step_name="extract_kpi",
            workflow_version="extraction-workflow/v1",
            provider_ref="mock",
            model_ref="mock-structured-v1",
        )
    assert provider.calls == 2


def test_refusal_is_not_abstention() -> None:
    provider = _ScriptedProvider([_refuse()])
    with pytest.raises(ProviderRefused):
        run_model_step(
            provider=provider,  # type: ignore[arg-type]
            spec=ROLE_SPECS[Role.KPI],
            evidence_blocks=[
                {"source_span_id": "22222222-2222-4222-8222-222222222222", "text": "REFUSE"}
            ],
            budget=RunBudget(),
            run_id="00000000-0000-4000-8000-000000000001",
            step_name="extract_kpi",
            workflow_version="extraction-workflow/v1",
            provider_ref="mock",
            model_ref="mock-structured-v1",
        )


def test_empty_valid_envelope_is_abstention() -> None:
    provider = _ScriptedProvider([_ok({"proposals": []})])
    result = run_model_step(
        provider=provider,  # type: ignore[arg-type]
        spec=ROLE_SPECS[Role.KPI],
        evidence_blocks=[
            {"source_span_id": "22222222-2222-4222-8222-222222222222", "text": "none"}
        ],
        budget=RunBudget(),
        run_id="00000000-0000-4000-8000-000000000001",
        step_name="extract_kpi",
        workflow_version="extraction-workflow/v1",
        provider_ref="mock",
        model_ref="mock-structured-v1",
    )
    assert isinstance(result.outcome, Abstention)
    assert result.attempts == 1
    # Root hash stable vs attempt hashes (single attempt → equal).
    assert result.root_input_hash == result.attempt_request_hashes[0]


def test_root_input_hash_stable_across_repair() -> None:
    provider = _ScriptedProvider(
        [
            _ok({"wrong": True}),
            _ok({"proposals": []}),
        ]
    )
    result = run_model_step(
        provider=provider,  # type: ignore[arg-type]
        spec=ROLE_SPECS[Role.KPI],
        evidence_blocks=[{"source_span_id": "22222222-2222-4222-8222-222222222222", "text": "x"}],
        budget=RunBudget(),
        run_id="00000000-0000-4000-8000-000000000001",
        step_name="extract_kpi",
        workflow_version="extraction-workflow/v1",
        provider_ref="mock",
        model_ref="mock-structured-v1",
    )
    assert provider.calls == 2
    assert result.root_input_hash == result.attempt_request_hashes[0]
    assert result.attempt_request_hashes[0] != result.attempt_request_hashes[1]
