"""Regression tests for PR #145 review blockers (checkpoint output + evidence FK)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.events import redact_payload
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.persist import PostgresPersistStore
from fel_workers.extraction.serialize import serialize_stage_output
from fel_workers.extraction.types import EvidenceBlock, ProposalDraft
from fel_workers.extraction.validate.pipeline import _evidence_rows


def test_stage_output_keeps_span_text_under_redaction() -> None:
    payload = {
        "step_name": "assemble_evidence",
        "input_hash": "sha256:" + "a" * 64,
        "stage_output": [
            {
                "source_span_id": "22222222-2222-4222-8222-222222222222",
                "document_version_id": "33333333-3333-4333-8333-333333333333",
                "text": "ARR was $100 million",
                "text_hash": sha256_hex("ARR was $100 million"),
            }
        ],
        "api_key": "should-go",
    }
    cleaned = redact_payload(payload)
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["stage_output"][0]["text"] == "ARR was $100 million"


def test_serialize_evidence_block_round_trip_shape() -> None:
    block = EvidenceBlock(
        source_span_id="22222222-2222-4222-8222-222222222222",
        document_version_id="33333333-3333-4333-8333-333333333333",
        text="hello",
        text_hash=sha256_hex("hello"),
    )
    serialized = serialize_stage_output([block])
    assert isinstance(serialized, list)
    assert serialized[0]["text"] == "hello"
    assert serialized[0]["document_version_id"].startswith("3333")


def test_evidence_rows_pin_document_version_from_assembled_map() -> None:
    clean = {
        "evidence": [{"source_span_id": "22222222-2222-4222-8222-222222222222", "role": "supports"}]
    }
    pinned = {
        "22222222-2222-4222-8222-222222222222": {
            "document_version_id": "33333333-3333-4333-8333-333333333333",
        }
    }
    rows = _evidence_rows(clean, evidence_by_span=pinned)
    assert rows[0]["document_version_id"] == "33333333-3333-4333-8333-333333333333"


def test_postgres_persist_rejects_missing_document_version_id() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)
    store = PostgresPersistStore(conn)
    draft = ProposalDraft(
        kind="kpi",
        metric_id="arr",
        payload={"kind": "kpi"},
        raw_payload_hash="sha256:" + "b" * 64,
        definition_hash="sha256:" + "c" * 64,
        comparability_key={},
        evidence=[{"source_span_id": "22222222-2222-4222-8222-222222222222", "role": "supports"}],
        id="44444444-4444-4444-8444-444444444444",
    )
    with pytest.raises(StepFailed, match="document_version_id"):
        store.persist_proposals(
            run_id="11111111-1111-4111-8111-111111111111",
            org_id="11111111-1111-4111-8111-111111111101",
            workspace_id="11111111-1111-4111-8111-111111111102",
            drafts=[draft],
        )
