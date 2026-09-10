"""Crash-resume + full mock workflow acceptance (M3-101/102/107)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.checkpoint import MemoryCheckpointStore
from fel_workers.extraction.events import MemoryEventStore, redact_log_payload
from fel_workers.extraction.handler import JOB_KIND_EXTRACTION_RUN, handle_extraction_run
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import (
    STAGE_ORDER,
    WORKFLOW_VERSION,
    EvidenceBlock,
    ExtractionRunRequest,
    WorkflowState,
)
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import FIXTURE_DOC, FIXTURE_ENTITY, FIXTURE_SPAN, sample_payload

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _request(**overrides: object) -> ExtractionRunRequest:
    base = ExtractionRunRequest(
        run_id=str(uuid4()),
        org_id=str(uuid4()),
        workspace_id=str(uuid4()),
        entity_id=FIXTURE_ENTITY,
        modes=("kpi",),
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        corpus_version_id=str(uuid4()),
        ontology_version="saas-metrics/v1",
        workflow_version=WORKFLOW_VERSION,
        provider="mock",
        model="mock-structured-v1",
        policy_id=str(uuid4()),
        input_manifest={"source_span_ids": [FIXTURE_SPAN]},
        input_hash=sha256_hex("manifest"),
        issuer_label="Example SaaS",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _evidence() -> list[EvidenceBlock]:
    text = "ARR was $100 million as of June 30, 2026."
    return [
        EvidenceBlock(
            source_span_id=FIXTURE_SPAN,
            document_version_id=FIXTURE_DOC,
            text=text,
            text_hash=sha256_hex(text),
            published_at=datetime(2026, 6, 30, tzinfo=UTC),
        )
    ]


def test_full_mock_workflow_proposals_needs_review() -> None:
    persist = MemoryPersistStore()
    state = WorkflowState(request=_request(), evidence=_evidence())
    deps = WorkflowDeps(
        structured_llm=MockStructuredLLMProvider(),
        persist=persist,
        evidence_loader=lambda _r: _evidence(),
    )
    out = run_extraction_workflow(state, deps)
    assert out.status == "waiting_review"
    assert out.validated
    assert all(p.state == "needs_review" for p in out.validated)
    assert all(p.state == "needs_review" for p in persist.proposals.values())
    assert persist.run_status[out.request.run_id] == "waiting_review"


def test_crash_after_every_stage_resumes_without_redo() -> None:
    """Inject a crash after each newly committed stage; resume must skip hashes.

    Each attempt gets its own run-row double. ``crash_after_stages`` is a
    HANDLED RuntimeError, which the workflow's catch-all lands as run
    ``failed`` — and terminal runs are final (#146): the consumer dead-letters
    that job rather than re-dispatching it, and a shared ``MemoryPersistStore``
    now (correctly) refuses every resume below. What this test exercises is the
    checkpoint/event stores' content-addressed skip — what a resume after
    PROCESS death (row still ``running``) reads — so those two are shared.
    """
    checkpoint = MemoryCheckpointStore()
    events = MemoryEventStore()
    llm = MockStructuredLLMProvider()
    request = _request()
    evidence = _evidence()

    # Count model calls via a thin wrapper.
    class CountingLLM:
        provider = llm.provider
        model = llm.model
        calls = 0

        def generate_structured(self, request):  # noqa: ANN001
            self.calls += 1
            return llm.generate_structured(request)

    counting = CountingLLM()
    executable = [
        s
        for s in STAGE_ORDER
        if s
        not in {
            "extract_guidance",
            "extract_revenue_driver",
        }
    ]

    for crash_at in range(1, len(executable) + 1):
        state = WorkflowState(request=request, evidence=list(evidence))
        deps = WorkflowDeps(
            structured_llm=counting,
            checkpoint=checkpoint,
            events=events,
            persist=MemoryPersistStore(),
            evidence_loader=lambda _r: list(evidence),
            crash_after_stages=crash_at,
        )
        try:
            run_extraction_workflow(state, deps)
        except RuntimeError as exc:
            assert "injected crash" in str(exc)
        else:
            # Final stages may complete without crash once all committed.
            break

    calls_before_final = counting.calls
    # Final clean run — should skip all succeeded stages (no new model calls
    # if classify/candidates/kpi already checkpointed).
    final_state = WorkflowState(request=request, evidence=list(evidence))
    persist = MemoryPersistStore()
    final = run_extraction_workflow(
        final_state,
        WorkflowDeps(
            structured_llm=counting,
            checkpoint=checkpoint,
            events=events,
            persist=persist,
            evidence_loader=lambda _r: list(evidence),
        ),
    )
    assert final.status == "waiting_review"
    assert counting.calls == calls_before_final
    succeeded = checkpoint.list_succeeded(run_id=request.run_id)
    assert {r.step_name for r in succeeded} >= {
        "validate_request",
        "assemble_evidence",
        "classify",
        "normalize",
        "persist_proposals",
    }


def test_handler_memory_path_and_job_kind_constant() -> None:
    assert JOB_KIND_EXTRACTION_RUN == "extraction_run"
    payload = sample_payload(modes=["kpi"])
    state = handle_extraction_run(None, MockStructuredLLMProvider(), payload)
    assert state.status in {"waiting_review", "succeeded"}


def test_redaction_strips_prompt_dumps() -> None:
    cleaned = redact_log_payload(
        {
            "prompt": "SECRET SYSTEM",
            "messages": [{"role": "user", "content": "filing text"}],
            "run_id": "ok",
            "api_key": "sk-secret",
        }
    )
    assert cleaned["prompt"] == "[redacted]"
    assert cleaned["messages"] == "[redacted]"
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["run_id"] == "ok"


@pytest.mark.parametrize("version", ["extraction-workflow/v1", "extraction-workflow/v2"])
def test_legacy_workflow_is_rejected_before_any_checkpoint_recovery(version) -> None:
    class NoRecovery(MemoryCheckpointStore):
        def load_succeeded(self, **kwargs):
            pytest.fail("old version reached checkpoint recovery")

    state = WorkflowState(request=replace(_request(), workflow_version=version))
    out = run_extraction_workflow(
        state, WorkflowDeps(structured_llm=MockStructuredLLMProvider(), checkpoint=NoRecovery())
    )
    assert out.status == "failed"
    assert "unsupported workflow version" in out.error["message"]
    assert out.stages == {}


def test_stage_input_hashes_pin_policy_and_component_versions(monkeypatch) -> None:
    from fel_workers.extraction import workflow
    from fel_workers.extraction.hashing import hash_json

    state = WorkflowState(request=_request())
    before = {
        s: hash_json(workflow._stage_input_payload(state, s)) for s in ("normalize", "validate")
    }
    monkeypatch.setattr(workflow, "UNIT_POLICY_VERSION", "future-policy")
    assert all(hash_json(workflow._stage_input_payload(state, s)) != before[s] for s in before)
    assert workflow._stage_input_payload(state, "normalize")["normalizer_version"] == "normalize/v2"
    assert workflow._stage_input_payload(state, "validate")["validator_version"] == "validate/v3"


@pytest.mark.parametrize(
    "pin,stages",
    [
        ("RANGE_POLICY_VERSION", ("normalize", "validate")),
        ("NORMALIZER_VERSION", ("normalize",)),
        ("VALIDATOR_VERSION", ("validate",)),
    ],
)
def test_range_and_component_pins_change_actual_stage_hashes(monkeypatch, pin, stages):
    from fel_workers.extraction import workflow
    from fel_workers.extraction.hashing import stage_input_hash

    state = WorkflowState(request=_request())

    def inputs(stage):
        return stage_input_hash(
            workflow_version=state.request.workflow_version,
            step_name=stage,
            payload=workflow._stage_input_payload(state, stage),
            run_id=state.request.run_id,
        )

    before = {s: inputs(s) for s in stages}
    monkeypatch.setattr(workflow, pin, "future-policy")
    assert all(inputs(s) != before[s] for s in stages)
