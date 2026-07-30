"""Shared fixtures for extraction worker tests (mock-only)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.hashing import sha256_hex

FIXTURE_SPAN = "22222222-2222-4222-8222-222222222222"
FIXTURE_ENTITY = "11111111-1111-4111-8111-111111111111"
FIXTURE_DOC = "33333333-3333-4333-8333-333333333333"


def make_ids() -> dict[str, str]:
    return {
        "run_id": str(uuid4()),
        "org_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "entity_id": FIXTURE_ENTITY,
        "policy_id": str(uuid4()),
    }


def sample_evidence(*, text: str = "ARR was $100 million as of June 30, 2026.") -> list[dict]:
    return [
        {
            "source_span_id": FIXTURE_SPAN,
            "document_version_id": FIXTURE_DOC,
            "text": text,
            "text_hash": sha256_hex(text),
            "published_at": "2026-06-30T00:00:00+00:00",
        }
    ]


def sample_payload(*, modes: list[str] | None = None, text: str | None = None) -> dict:
    ids = make_ids()
    evidence = sample_evidence(text=text) if text is not None else sample_evidence()
    return {
        **ids,
        "modes": modes or ["kpi"],
        "as_of": datetime(2026, 7, 1, tzinfo=UTC).isoformat(),
        "corpus_version_id": str(uuid4()),
        "ontology_version": "saas-metrics/v1",
        "workflow_version": "extraction-workflow/v1",
        "provider": "mock",
        "model": "mock-structured-v1",
        "input_manifest": {"source_span_ids": [FIXTURE_SPAN]},
        "issuer_label": "Example SaaS",
        "evidence": evidence,
    }


@pytest.fixture()
def sample_run_payload() -> dict:
    return sample_payload(modes=["kpi"])


@pytest.fixture()
def structured_llm() -> MockStructuredLLMProvider:
    return MockStructuredLLMProvider()
