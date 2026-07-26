"""Unit tests for M3 review fixes (org scoping, schema, conflicts)."""

from __future__ import annotations

import inspect
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import SchemaInvalid
from fel_workers.extraction.persist import MemoryPersistStore, PostgresPersistStore
from fel_workers.extraction.roles import ROLE_SPECS, Role
from fel_workers.extraction.runner import run_model_step
from fel_workers.extraction.types import ConflictDraft
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.duplicates import conflict_key_for

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)


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


def test_set_run_status_requires_org_id() -> None:
    store = MemoryPersistStore()
    sig = inspect.signature(store.set_run_status)
    assert "org_id" in sig.parameters
    with pytest.raises(TypeError):
        store.set_run_status(run_id=str(uuid4()), status="failed")  # type: ignore[call-arg]
    store.set_run_status(run_id=str(uuid4()), org_id=str(uuid4()), status="succeeded")


def test_postgres_set_run_status_filters_by_org_id() -> None:
    conn = MagicMock()
    store = PostgresPersistStore(conn)
    run_id, org_id = str(uuid4()), str(uuid4())
    store.set_run_status(run_id=run_id, org_id=org_id, status="failed", error={"code": "x"})
    sql = conn.execute.call_args[0][0]
    params = conn.execute.call_args[0][1]
    assert "WHERE id = %s AND org_id = %s" in " ".join(sql.split())
    assert params[-2:] == (run_id, org_id)


def test_conflict_members_insert_includes_org_id() -> None:
    """After conflict upsert, members are inserted with resolved id + org_id."""
    org_id = str(uuid4())
    workspace_id = str(uuid4())
    conflict_id = str(uuid4())
    proposal_a, proposal_b = str(uuid4()), str(uuid4())

    executed: list[tuple[str, tuple[Any, ...]]] = []

    class _Conn:
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
            executed.append((sql, params))

            class _Result:
                def fetchone(self_inner) -> tuple[str] | None:  # noqa: N805
                    if "FROM extraction_conflicts" in sql:
                        return (conflict_id,)
                    return None

            return _Result()

    store = PostgresPersistStore(_Conn())  # type: ignore[arg-type]
    with patch(
        "fel_workers.extraction.persist.assert_workspace_ownership",
        lambda *a, **k: None,
    ):
        out = store.persist_conflicts(
            org_id=org_id,
            workspace_id=workspace_id,
            drafts=[
                ConflictDraft(
                    conflict_key="ck-test",
                    reason_codes=["value_disagreement"],
                    member_proposal_ids=[proposal_a, proposal_b],
                )
            ],
        )

    assert out and out[0].id == conflict_id
    member_calls = [
        (sql, params) for sql, params in executed if "extraction_conflict_members" in sql
    ]
    assert len(member_calls) == 2
    for sql, params in member_calls:
        assert "org_id" in sql
        assert params[0] == conflict_id
        assert params[2] == org_id
        assert params[1] in {proposal_a, proposal_b}


def test_junk_proposals_raise_schema_invalid_not_abstention() -> None:
    junk = {"proposals": [{"not": "a valid payload"}, {"also": "junk"}]}
    provider = _ScriptedProvider([_ok(junk), _ok(junk)])
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


def test_nrr_distinct_base_quantity_no_false_conflict() -> None:
    base = json.loads(FIXTURES.read_text())["kpi"]
    period = {
        "type": "duration",
        "start": "2025-07-01",
        "end": "2026-06-30",
        "fiscal_period": "TTM",
    }
    nrr_arr = {
        **base,
        "metric_id": "nrr",
        "value": "120",
        "unit": "ratio",
        "currency": None,
        "scale": 0,
        "period": period,
        "qualifiers": {
            "base_quantity": "arr",
            "window": "ttm_point_in_time",
            "population_scope": "all",
        },
    }
    nrr_acv = {
        **nrr_arr,
        "value": "110",
        "raw_value": "110%",
        "qualifiers": {
            "base_quantity": "acv",
            "window": "ttm_point_in_time",
            "population_scope": "all",
        },
    }
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-000000000097",
        payloads=[nrr_arr, nrr_acv],
    )
    assert len(result.proposals) == 2
    keys = {
        conflict_key_for(
            d.payload,
            ontology_comparability_key=(
                d.comparability_key.get("key")
                if isinstance(d.comparability_key.get("key"), str)
                else None
            ),
        )
        for d in result.proposals
    }
    assert len(keys) == 2
    assert not any("value_disagreement" in c.reason_codes for c in result.conflicts)


def test_conflict_key_uses_ontology_comparability() -> None:
    payload = {
        "kind": "kpi",
        "metric_id": "nrr",
        "entity_id": "e",
        "period": {"type": "instant"},
    }
    a = conflict_key_for(payload, ontology_comparability_key="metric_id=nrr|base_quantity=arr")
    b = conflict_key_for(payload, ontology_comparability_key="metric_id=nrr|base_quantity=acv")
    assert a != b
