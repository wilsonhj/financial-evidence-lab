"""First-ingest evidence integrity (#60 review residual).

`stages.io.restore_output` re-hashes span text on the crash-resume path, but the
ingest path only ever checked that ``text_hash`` carried a ``sha256:``
prefix — never that the digest described the text. A caller-supplied wrong
hash was therefore accepted at stage one and only surfaced after a crash,
so every proposal from an uncrashed run carried a citation hash that need
not describe its own evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import MemoryPersistStore
from fel_workers.extraction.types import EvidenceBlock, ExtractionRunRequest, WorkflowState
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

from .conftest import FIXTURE_DOC, FIXTURE_ENTITY, FIXTURE_SPAN

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SPAN_TEXT = "ARR was $100 million as of June 30, 2026."


def _request() -> ExtractionRunRequest:
    return ExtractionRunRequest(
        run_id=str(uuid4()),
        org_id=str(uuid4()),
        workspace_id=str(uuid4()),
        entity_id=FIXTURE_ENTITY,
        modes=("kpi",),
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        corpus_version_id=str(uuid4()),
        ontology_version="saas-metrics/v1",
        workflow_version="extraction-workflow/v1",
        provider="mock",
        model="mock-structured-v1",
        policy_id=str(uuid4()),
        input_manifest={"source_span_ids": [FIXTURE_SPAN]},
        input_hash=sha256_hex("manifest"),
        issuer_label="Example SaaS",
    )


def _block(text: str, text_hash: str) -> EvidenceBlock:
    return EvidenceBlock(
        source_span_id=FIXTURE_SPAN,
        document_version_id=FIXTURE_DOC,
        text=text,
        text_hash=text_hash,
        published_at=datetime(2026, 6, 30, tzinfo=UTC),
    )


def _run(block: EvidenceBlock) -> tuple[WorkflowState, MemoryPersistStore]:
    persist = MemoryPersistStore()
    state = WorkflowState(request=_request(), evidence=[block])
    deps = WorkflowDeps(
        structured_llm=MockStructuredLLMProvider(),
        persist=persist,
        evidence_loader=lambda _r: [block],
    )
    return run_extraction_workflow(state, deps), persist


def test_ingest_rejects_evidence_whose_hash_does_not_describe_its_text() -> None:
    """A well-formed but WRONG digest must fail closed at ingest.

    The hash is the citation's content address: if it does not describe the
    text, every proposal the run emits cites evidence it cannot prove.
    """
    wrong = sha256_hex("some entirely different filing paragraph")
    out, persist = _run(_block(SPAN_TEXT, wrong))

    assert out.status == "failed"
    assert out.error is not None
    assert "text_hash" in out.error["message"]
    assert persist.run_status[out.request.run_id] == "failed"
    assert not persist.proposals


def test_ingest_still_rejects_a_missing_sha256_prefix() -> None:
    """The pre-existing malformed-hash guard must survive the stricter check."""
    out, _ = _run(_block(SPAN_TEXT, "deadbeef"))

    assert out.status == "failed"
    assert out.error is not None


def test_ingest_accepts_evidence_whose_hash_matches() -> None:
    """Control: the happy path is untouched, so the guard cannot be vacuous."""
    out, persist = _run(_block(SPAN_TEXT, sha256_hex(SPAN_TEXT)))

    assert out.status == "waiting_review"
    assert persist.proposals
