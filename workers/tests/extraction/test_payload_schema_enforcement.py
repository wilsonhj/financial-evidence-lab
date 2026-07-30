"""The frozen contract schema is enforced, not merely loadable.

`packages/contracts/schemas/extraction-payload.schema.json` sets
`additionalProperties: false` on every payload variant, but `validate_payload_item`
was a hand-rolled required-field checker that never consulted it — so any extra key
the model invented rode through normalize, validate and persist untouched. That is
what made a model-supplied `citation_status` reachable at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fel_workers.extraction.roles.base import ROLE_SPECS
from fel_workers.extraction.types import Role
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.schema import (
    WORKER_EXTENSION_KEYS,
    allowed_payload_keys,
    load_extraction_payload_schema,
    validate_payload_item,
)

from .conftest import FIXTURE_DOC, FIXTURE_ENTITY, FIXTURE_SPAN

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)


def _fixture(name: str) -> dict[str, Any]:
    data = json.loads(_FIXTURES.read_text(encoding="utf-8"))
    payload = data[name]
    assert isinstance(payload, dict)
    return dict(payload)


# ---------------------------------------------------------------------------
# Defect H — unknown top-level keys are rejected, contract extensions are not.
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_is_rejected() -> None:
    payload = _fixture("kpi")
    payload["citation_status"] = "verified"

    errors = validate_payload_item(payload)
    assert "unknown field not permitted by extraction-payload/v1: citation_status" in errors


def test_unknown_key_is_rejected_for_every_variant() -> None:
    for name in ("kpi", "guidance_point", "guidance_qualitative", "revenue_driver"):
        payload = _fixture(name)
        payload["confidence"] = 0.99
        errors = validate_payload_item(payload)
        assert "unknown field not permitted by extraction-payload/v1: confidence" in errors, name


def test_contract_fixtures_stay_clean() -> None:
    """Every frozen fixture must still validate — enforcement must not over-reach."""
    data = json.loads(_FIXTURES.read_text(encoding="utf-8"))
    for key, payload in data.items():
        if key == "note" or not isinstance(payload, dict):
            continue
        assert validate_payload_item(payload) == [], key


def test_pipeline_extension_keys_are_allowed() -> None:
    """`evidence` and `source_span_ids` are read by the pipeline and are not contract keys."""
    payload = _fixture("kpi")
    payload["evidence"] = [{"source_span_id": FIXTURE_SPAN, "document_version_id": FIXTURE_DOC}]
    assert validate_payload_item(payload) == []

    other = _fixture("kpi")
    other["source_span_ids"] = [FIXTURE_SPAN]
    assert validate_payload_item(other) == []


def test_allowed_keys_are_derived_from_the_frozen_contract_schema() -> None:
    """No hand-maintained copy: the allowed set is the contract's own property list."""
    schema = load_extraction_payload_schema()
    kpi_keys = set(schema["$defs"]["kpi"]["properties"])
    allowed = allowed_payload_keys("kpi", shape=None)

    assert kpi_keys <= allowed
    assert allowed - kpi_keys == set(WORKER_EXTENSION_KEYS)


def test_unknown_key_surfaces_as_a_reviewer_blocker() -> None:
    payload = _fixture("kpi")
    payload["entity_id"] = FIXTURE_ENTITY
    payload["qualifiers"] = {
        "currency": "USD",
        "construction": "reported_arr",
        "scope": "consolidated",
    }
    payload["review_priority"] = "normal"

    result = validate_proposals(run_id=_RUN_ID, payloads=[payload])
    blockers = result.proposals[0].validation_summary["blockers"]
    assert "unknown field not permitted by extraction-payload/v1: review_priority" in blockers
    assert result.proposals[0].validation_summary["ok"] is False


# ---------------------------------------------------------------------------
# Defect H — `citation_status` is a pipeline control field, never model input.
# ---------------------------------------------------------------------------


def test_model_supplied_citation_status_in_an_evidence_row_is_rejected() -> None:
    payload = _fixture("kpi")
    payload["evidence"] = [
        {
            "source_span_id": FIXTURE_SPAN,
            "document_version_id": FIXTURE_DOC,
            "citation_status": "verified",
        }
    ]

    errors = validate_payload_item(payload)
    assert "evidence[0]: citation_status is set by the pipeline, not the model" in errors


def test_model_supplied_citation_status_never_reaches_a_draft_row() -> None:
    """Rejecting is not enough: a blocker does not stop the draft being persisted."""
    payload = _fixture("kpi")
    payload["entity_id"] = FIXTURE_ENTITY
    payload["evidence"] = [
        {
            "source_span_id": FIXTURE_SPAN,
            "document_version_id": FIXTURE_DOC,
            "citation_status": "verified",
        }
    ]

    result = validate_proposals(run_id=_RUN_ID, payloads=[payload])
    row = result.proposals[0].evidence[0]
    assert row["citation_status"] != "verified"
    # The raw payload keeps the model's words verbatim; only the graded row is ours.
    assert result.proposals[0].payload["evidence"][0]["citation_status"] == "verified"


# ---------------------------------------------------------------------------
# Defect H — the envelope handed to the provider constrains proposal items.
# ---------------------------------------------------------------------------


def test_role_envelope_names_the_keys_a_proposal_may_carry() -> None:
    envelope = cast(dict[str, Any], ROLE_SPECS[Role.KPI].json_schema)
    items = envelope["properties"]["proposals"]["items"]
    names = items.get("propertyNames", {}).get("enum")

    assert names, "proposal items must not be an unconstrained object"
    union: set[str] = set(WORKER_EXTENSION_KEYS)
    schema = load_extraction_payload_schema()
    for variant in ("kpi", "guidanceBase", "revenueDriver"):
        union |= set(schema["$defs"][variant]["properties"])
    union |= {"shape", "value", "low", "high", "text"}

    assert set(names) == union, "envelope key list has drifted from the frozen contract"
