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
    result = MockStructuredLLMProvider(refuse=True).generate_structured(_req("kpi"))
    assert result.refused is True
    assert result.parsed is None


def _two_turn_req(system: str, user: str) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        schema_name="kpi",
        schema_version="1.0.0",
        json_schema={"type": "object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_output_tokens=64,
    )


def test_abstain_hook_ignores_untrusted_evidence_text() -> None:
    """ABSTAIN is a SYSTEM-message test switch. The user turn carries filing
    text, which is attacker-influenced: if it could trigger the hook, a
    document containing the word would suppress every extraction on the run
    (prompt-injection DoS)."""
    result = MockStructuredLLMProvider().generate_structured(
        _two_turn_req("extract kpis", "Directors may ABSTAIN from the vote.")
    )
    assert result.parsed is not None
    assert result.parsed["proposals"]


def test_refusal_hook_ignores_untrusted_evidence_text() -> None:
    """Refusal is a CONSTRUCTOR switch, never message content. The user turn
    carries filing/question text, which is attacker-influenced: if it could
    trigger the hook, a document containing the word would null ``parsed`` and
    refuse every step on the run (prompt-injection DoS)."""
    result = MockStructuredLLMProvider().generate_structured(
        _two_turn_req("extract kpis", "The board voted to REFUSE the merger.")
    )
    assert result.refused is False
    assert result.parsed is not None
    assert result.parsed["proposals"]


def test_refusal_hook_cannot_be_triggered_by_any_message() -> None:
    """Stricter than the ABSTAIN hook: no turn, system included, flips refusal."""
    result = MockStructuredLLMProvider().generate_structured(
        _two_turn_req("REFUSE", "ARR was $100 million.")
    )
    assert result.refused is False
    assert result.parsed is not None


def test_abstain_hook_still_fires_from_the_system_message() -> None:
    result = MockStructuredLLMProvider().generate_structured(
        _two_turn_req("ABSTAIN", "ARR was $100 million.")
    )
    assert result.parsed is not None
    assert result.parsed["proposals"] == []


def test_mock_unknown_schema_keeps_legacy_shape() -> None:
    result = MockStructuredLLMProvider().generate_structured(_req("extraction-payload"))
    assert result.parsed is not None
    assert result.parsed["mock"] is True
