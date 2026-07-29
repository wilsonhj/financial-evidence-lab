"""`citation_status` is computed from pinned evidence, never taken from the model.

`extraction_proposal_evidence` is append-only — `db/migrations/0004_extraction_core.sql`
makes UPDATE and DELETE raise — so whatever grade a run writes is permanent and
uncorrectable. These tests pin the two properties that makes safe:

* the grade is derived by code from the pinned evidence alone, and
* no JSON shape the model can choose changes the grade it receives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.handler import handle_extraction_run
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.types import (
    WORKFLOW_VERSION,
    EvidenceBlock,
    ExtractionRunRequest,
    ProposalDraft,
    WorkflowState,
)
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.pipeline import citation_status_for
from fel_workers.extraction.workflow import _stage_verify_citations

from .conftest import FIXTURE_DOC, FIXTURE_ENTITY, FIXTURE_SPAN

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_SPAN = "44444444-4444-4444-8444-444444444444"
_PINNED_TEXT = "ARR was $100 million as of June 30, 2026."


def _evidence_block() -> EvidenceBlock:
    return EvidenceBlock(
        source_span_id=FIXTURE_SPAN,
        document_version_id=FIXTURE_DOC,
        text=_PINNED_TEXT,
        text_hash=sha256_hex(_PINNED_TEXT),
    )


def _pinned() -> dict[str, dict[str, Any]]:
    block = _evidence_block()
    return {
        block.source_span_id: {
            "document_version_id": block.document_version_id,
            "text": block.text,
            "text_hash": block.text_hash,
        }
    }


def _request() -> ExtractionRunRequest:
    return ExtractionRunRequest(
        run_id=_RUN_ID,
        org_id="55555555-5555-4555-8555-555555555555",
        workspace_id="66666666-6666-4666-8666-666666666666",
        entity_id=FIXTURE_ENTITY,
        modes=("kpi",),
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        corpus_version_id="77777777-7777-4777-8777-777777777777",
        ontology_version="saas-metrics/v1",
        workflow_version=WORKFLOW_VERSION,
        provider="mock",
        model="mock-structured-v1",
        policy_id="88888888-8888-4888-8888-888888888888",
        input_manifest={"source_span_ids": [FIXTURE_SPAN]},
        input_hash="sha256:" + "0" * 64,
    )


def _state(drafts: list[ProposalDraft]) -> WorkflowState:
    state = WorkflowState(request=_request())
    state.evidence = [_evidence_block()]
    state.validated = drafts
    return state


def _bare_draft(evidence_rows: list[dict[str, Any]]) -> ProposalDraft:
    """A draft carrying exactly the citation rows under test."""
    return ProposalDraft(
        kind="kpi",
        metric_id="arr",
        payload={},
        raw_payload_hash=sha256_hex("x"),
        definition_hash=sha256_hex(""),
        comparability_key={"key": None, "fields": []},
        record_confidence=Decimal("0"),
        evidence=evidence_rows,
    )


def _kpi(evidence: Any, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
        "evidence": evidence,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Defect A — the model must not be able to grade its own citations.
# ---------------------------------------------------------------------------


def test_row_without_a_source_span_id_is_never_verified() -> None:
    """A row that identifies no span proves nothing, so it cannot be `verified`.

    The old `if span_id and span_id not in evidence_ids` short-circuited to the
    `else` branch for a falsy span id and stamped `verified`.
    """
    draft = _bare_draft([{"role": "supports"}])
    out = _stage_verify_citations(_state([draft]))

    assert draft.evidence[0]["citation_status"] == "invalid"
    assert out["invalid_citations"] == 1


def test_row_with_an_empty_source_span_id_is_never_verified() -> None:
    draft = _bare_draft([{"source_span_id": "", "role": "supports"}])
    out = _stage_verify_citations(_state([draft]))

    assert draft.evidence[0]["citation_status"] == "invalid"
    assert out["invalid_citations"] == 1


def test_model_supplied_verified_is_overwritten_not_preserved() -> None:
    """`setdefault` let a model-supplied grade survive; the grade is now assigned."""
    draft = _bare_draft(
        [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "citation_status": "verified",
            }
        ]
    )
    _stage_verify_citations(_state([draft]))

    # Span membership alone is not proof the quoted content is right.
    assert draft.evidence[0]["citation_status"] == "partial"


def test_model_supplied_verified_on_an_unpinned_span_becomes_invalid() -> None:
    draft = _bare_draft([{"source_span_id": _OTHER_SPAN, "citation_status": "verified"}])
    out = _stage_verify_citations(_state([draft]))

    assert draft.evidence[0]["citation_status"] == "invalid"
    assert out["invalid_citations"] == 1


def test_string_and_dict_citations_to_the_same_span_grade_identically() -> None:
    """Choosing a JSON shape must not change the grade a citation earns."""
    as_string = _kpi([FIXTURE_SPAN])
    as_dict = _kpi([{"source_span_id": FIXTURE_SPAN, "document_version_id": FIXTURE_DOC}])
    result = validate_proposals(
        run_id=_RUN_ID, payloads=[as_string, as_dict], evidence_by_span=_pinned()
    )
    assert len(result.proposals) == 2

    _stage_verify_citations(_state(result.proposals))
    statuses = [p.evidence[0]["citation_status"] for p in result.proposals]
    assert statuses == ["partial", "partial"]


def test_pinned_span_without_an_asserted_hash_is_partial() -> None:
    draft = _bare_draft([{"source_span_id": FIXTURE_SPAN, "document_version_id": FIXTURE_DOC}])
    out = _stage_verify_citations(_state([draft]))

    assert draft.evidence[0]["citation_status"] == "partial"
    assert out["invalid_citations"] == 0
    assert out["partial_citations"] == 1


def test_a_matching_asserted_text_hash_earns_verified() -> None:
    """The one code-provable citation: the row asserts the span's content address."""
    draft = _bare_draft(
        [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "text_hash": sha256_hex(_PINNED_TEXT),
            }
        ]
    )
    out = _stage_verify_citations(_state([draft]))

    assert draft.evidence[0]["citation_status"] == "verified"
    assert out["verified_citations"] == 1


def test_a_mismatched_asserted_text_hash_is_invalid() -> None:
    draft = _bare_draft(
        [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "text_hash": sha256_hex("ARR was $900 million as of June 30, 2026."),
            }
        ]
    )
    out = _stage_verify_citations(_state([draft]))

    assert draft.evidence[0]["citation_status"] == "invalid"
    assert out["invalid_citations"] == 1


def test_invalid_citations_counts_every_downgraded_row() -> None:
    """The old counter skipped falsy span ids entirely and reported a clean run."""
    draft = _bare_draft(
        [
            {"role": "supports"},  # no span id at all
            {"source_span_id": _OTHER_SPAN},  # not pinned
            {
                "source_span_id": FIXTURE_SPAN,
                "text_hash": sha256_hex("something else"),
            },  # lying hash
            {"source_span_id": FIXTURE_SPAN},  # honest, unproven
        ]
    )
    out = _stage_verify_citations(_state([draft]))

    assert [row["citation_status"] for row in draft.evidence] == [
        "invalid",
        "invalid",
        "invalid",
        "partial",
    ]
    assert out["invalid_citations"] == 3
    assert out["partial_citations"] == 1
    assert out["verified_citations"] == 0


def test_grading_is_the_same_function_the_validator_uses() -> None:
    """One rule, so a rebuilt draft on resume cannot disagree with the stage."""
    pinned = _pinned()
    assert citation_status_for({"source_span_id": FIXTURE_SPAN}, evidence_by_span=pinned) == (
        "partial"
    )
    assert citation_status_for({}, evidence_by_span=pinned) == "invalid"
    assert citation_status_for({"source_span_id": _OTHER_SPAN}, evidence_by_span=pinned) == (
        "invalid"
    )


def test_validate_proposals_grades_rows_without_the_workflow_stage() -> None:
    """Crash-resume rebuilds drafts outside `verify_citations`; those rows still grade."""
    payload = _kpi([{"source_span_id": FIXTURE_SPAN, "citation_status": "verified"}])
    result = validate_proposals(run_id=_RUN_ID, payloads=[payload], evidence_by_span=_pinned())

    assert result.proposals[0].evidence[0]["citation_status"] == "partial"


def test_mock_e2e_run_never_self_grades_a_citation_verified(
    sample_run_payload: dict[str, Any], structured_llm: MockStructuredLLMProvider
) -> None:
    state = handle_extraction_run(None, structured_llm, sample_run_payload, use_memory_stores=True)

    assert state.error is None, state.error
    assert state.validated
    for draft in state.validated:
        assert draft.evidence
        for row in draft.evidence:
            assert row["citation_status"] == "partial"
