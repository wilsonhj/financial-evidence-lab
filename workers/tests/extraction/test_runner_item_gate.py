"""The runner's per-item gate must actually gate (P1-2b).

Two holes: one valid item admitted every malformed sibling verbatim *and*
suppressed the single repair attempt, and every proposal role shares
``role_envelope.v1.json`` so no role was pinned to its own ``kind``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from fel_providers.interfaces import (
    StructuredGenerationRequest,
    StructuredModelResult,
)
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import SchemaInvalid
from fel_workers.extraction.roles import ROLE_SPECS, Role
from fel_workers.extraction.runner import run_model_step

from .conftest import FIXTURE_ENTITY, FIXTURE_SPAN


class _ScriptedProvider:
    provider = "mock"
    model = "mock-structured-v1"

    def __init__(self, envelopes: list[dict[str, Any]]) -> None:
        self._envelopes = list(envelopes)
        self.calls = 0

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        del request
        self.calls += 1
        parsed = self._envelopes.pop(0)
        return StructuredModelResult(
            provider="mock",
            model="mock-structured-v1",
            response_id=f"r-{self.calls}",
            parsed=parsed,
            refused=False,
            refusal=None,
            input_tokens=3,
            output_tokens=3,
            estimated_cost_usd=Decimal("0"),
            raw={},
        )


def _valid_kpi() -> dict[str, Any]:
    return {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": FIXTURE_ENTITY,
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "value": "100",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30", "fiscal_period": "FY2026-Q2"},
        "dimensions": {},
        "definition": "Annual recurring revenue",
        "qualifiers": {"currency": "USD", "construction": "ARR"},
        "reported_or_derived": "reported",
    }


def _valid_guidance() -> dict[str, Any]:
    return {
        "schema_version": "extraction-payload/v1",
        "kind": "guidance",
        "entity_id": FIXTURE_ENTITY,
        "issuer_label": "Example SaaS",
        "metric_id": "revenue",
        "raw_value": "approximately $120 million",
        "shape": "point",
        "value": "120",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "forecast", "end": "2026-09-30", "fiscal_period": "FY2026-Q3"},
        "dimensions": {},
        "definition": None,
        "qualifiers": {},
        "reported_or_derived": "management_assertion",
    }


def _step(provider: _ScriptedProvider, role: Role, step_name: str) -> Any:
    return run_model_step(
        provider=provider,  # type: ignore[arg-type]
        spec=ROLE_SPECS[role],
        evidence_blocks=[{"source_span_id": FIXTURE_SPAN, "text": "x"}],
        budget=RunBudget(),
        run_id="00000000-0000-4000-8000-000000000001",
        step_name=step_name,
        workflow_version="extraction-workflow/v1",
        provider_ref="mock",
        model_ref="mock-structured-v1",
    )


def test_one_valid_item_does_not_admit_malformed_siblings() -> None:
    """A mixed batch must repair once, then fail — never ride through."""
    mixed = {"proposals": [_valid_kpi(), {"kind": "kpi"}], "notes": None}
    provider = _ScriptedProvider([mixed, dict(mixed)])

    with pytest.raises(SchemaInvalid) as excinfo:
        _step(provider, Role.KPI, "extract_kpi")

    assert provider.calls == 2, "the repair attempt must not be suppressed"
    assert "proposals[1]" in str(excinfo.value)


def test_mixed_batch_accepts_a_clean_repair() -> None:
    """One repair is still all the runner gets, and a clean retry is accepted."""
    mixed = {"proposals": [_valid_kpi(), {"kind": "kpi"}], "notes": None}
    clean = {"proposals": [_valid_kpi()], "notes": None}
    provider = _ScriptedProvider([mixed, clean])

    result = _step(provider, Role.KPI, "extract_kpi")

    assert provider.calls == 2
    assert result.attempts == 2
    assert result.outcome == clean


def test_kpi_role_may_not_return_guidance_items() -> None:
    """All three proposal roles share one envelope schema; kind is the gate."""
    envelope = {"proposals": [_valid_guidance()], "notes": None}
    provider = _ScriptedProvider([envelope, dict(envelope)])

    with pytest.raises(SchemaInvalid) as excinfo:
        _step(provider, Role.KPI, "extract_kpi")

    assert provider.calls == 2
    assert "kind must be 'kpi'" in str(excinfo.value)


def test_guidance_role_still_accepts_its_own_kind() -> None:
    envelope = {"proposals": [_valid_guidance()], "notes": None}
    provider = _ScriptedProvider([envelope])

    result = _step(provider, Role.GUIDANCE, "extract_guidance")

    assert provider.calls == 1
    assert result.outcome == envelope
