"""Mock structured provider returns role envelopes (M3 mock extension)."""

from __future__ import annotations

from fel_providers.interfaces import StructuredGenerationRequest
from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.validate.schema import validate_payload_item


def _req(schema_name: str, content: str = "extract") -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        schema_name=schema_name,
        schema_version="1.0.0",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": content}],
        max_output_tokens=64,
    )


def test_mock_classifier_envelope() -> None:
    result = MockStructuredLLMProvider().generate_structured(_req("classifier"))
    assert result.refused is False
    assert result.parsed is not None
    assert "document_type" in result.parsed
    assert "relevant_modes" in result.parsed


def test_mock_kpi_uses_contract_fixture() -> None:
    result = MockStructuredLLMProvider().generate_structured(_req("kpi"))
    assert result.parsed is not None
    proposals = result.parsed["proposals"]
    assert isinstance(proposals, list) and proposals
    assert validate_payload_item(proposals[0]) == []  # type: ignore[arg-type]
    assert proposals[0]["qualifiers"].get("construction")  # type: ignore[index]


def test_mock_refusal_preserved() -> None:
    result = MockStructuredLLMProvider().generate_structured(_req("kpi", "REFUSE now"))
    assert result.refused is True
    assert result.parsed is None


def test_mock_unknown_schema_keeps_legacy_shape() -> None:
    result = MockStructuredLLMProvider().generate_structured(_req("extraction-payload"))
    assert result.parsed is not None
    assert result.parsed["mock"] is True
