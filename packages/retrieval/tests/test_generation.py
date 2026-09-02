"""Unit tests for structured claim generation (M2-020 / T0207, #193)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_providers.mocks import MockStructuredLLMProvider
from fel_retrieval.generation import (
    CLAIM_JSON_SCHEMA,
    CLAIM_SCHEMA_NAME,
    CLAIM_SCHEMA_VERSION,
    CLAIM_STATUSES,
    ClaimCitation,
    ContextItem,
    GeneratedClaim,
    GenerationContractError,
    NumericTuple,
    StructuredClaimGenerator,
)

AS_OF = "2026-01-01T00:00:00+00:00"


def _ctx(
    item_id: str, text: str, *, span: str = "span-1", numeric: NumericTuple | None = None
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        kind="passage",
        text=text,
        source_span_id=span,
        document_version_id="dv-1",
        numeric=numeric,
    )


class StubProvider:
    """Returns a fixed parsed object, recording the request it was handed."""

    provider = "stub"
    model = "stub-v1"

    def __init__(self, parsed: dict[str, Any] | None, *, refused: bool = False) -> None:
        self._parsed = parsed
        self._refused = refused
        self.request: StructuredGenerationRequest | None = None

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        self.request = request
        return StructuredModelResult(
            provider=self.provider,
            model=self.model,
            response_id="stub-1",
            parsed=self._parsed,
            refused=self._refused,
            refusal="stub-refusal" if self._refused else None,
            input_tokens=7,
            output_tokens=3,
            estimated_cost_usd=Decimal("0"),
            raw={},
        )


# --- schema identity -------------------------------------------------------
def test_request_schema_matches_the_claims_output_contract() -> None:
    """The schema sent to the provider is claims-output/v1, not a local variant."""
    contract = (
        Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "claims-output.schema.json"
    )
    if not contract.is_file():  # pragma: no cover - contracts workspace absent
        pytest.skip("contracts package not present")
    loaded = json.loads(contract.read_text(encoding="utf-8"))
    body = {
        key: value
        for key, value in loaded.items()
        if key not in {"$schema", "$id", "x-fel-version", "title", "description"}
    }
    assert _strip_descriptions(body) == CLAIM_JSON_SCHEMA
    assert loaded["$id"].endswith(f"{CLAIM_SCHEMA_NAME}/{CLAIM_SCHEMA_VERSION}")


def _strip_descriptions(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_descriptions(item) for item in node]
    return node


# --- provider JSON is consumed --------------------------------------------
def test_claims_come_from_provider_json_and_are_grounded() -> None:
    context = [
        _ctx("11111111-1111-4111-8111-111111111111", "Revenue was $100 million."),
        _ctx("22222222-2222-4222-8222-222222222222", "Net income was $28 million."),
    ]
    provider = StubProvider(
        {
            "claims": [
                {
                    "text": "Revenue was $100 million.",
                    "citations": [
                        {"item_id": context[0].item_id, "quote": "Revenue was $100 million"}
                    ],
                    "numeric": {"value": "100", "unit": "USD", "period": "FY2026-Q2"},
                }
            ],
            "abstain": None,
        }
    )
    result = StructuredClaimGenerator(provider).generate("q", context, as_of=AS_OF)

    assert provider.request is not None
    assert provider.request.schema_name == CLAIM_SCHEMA_NAME
    assert provider.request.json_schema == CLAIM_JSON_SCHEMA
    # Only the claim the provider actually returned — not one per context item.
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.text == "Revenue was $100 million."
    assert claim.status == "unsupported"  # proposed only; verification decides
    assert claim.status in CLAIM_STATUSES
    assert claim.confidence is None  # verification sets it, never the generator
    assert claim.citations[0].item_id == context[0].item_id
    assert claim.citations[0].source_span_id == context[0].source_span_id
    assert claim.citations[0].quote == "Revenue was $100 million"
    assert claim.numeric == NumericTuple(Decimal("100"), "USD", "FY2026-Q2", 0)
    assert (result.input_tokens, result.output_tokens) == (7, 3)


def test_numeric_scale_and_defaults_come_from_the_cited_evidence() -> None:
    evidence = NumericTuple(Decimal("100"), "USD", "FY2026-Q2", 6)
    context = [_ctx("item-1", "Revenue was $100 million.", numeric=evidence)]
    provider = StubProvider(
        {
            "claims": [
                {
                    "text": "Revenue was $100 million.",
                    "citations": [{"item_id": "item-1", "quote": "Revenue"}],
                    "numeric": {"value": "100", "unit": None, "period": None},
                }
            ],
            "abstain": None,
        }
    )
    claim = StructuredClaimGenerator(provider).generate("q", context, as_of=AS_OF).claims[0]
    assert claim.numeric == evidence


def test_unknown_item_id_is_a_contract_violation() -> None:
    provider = StubProvider(
        {
            "claims": [
                {
                    "text": "Revenue was $100 million.",
                    "citations": [{"item_id": "ghost", "quote": "Revenue"}],
                    "numeric": None,
                }
            ],
            "abstain": None,
        }
    )
    with pytest.raises(GenerationContractError) as excinfo:
        StructuredClaimGenerator(provider).generate(
            "q", [_ctx("item-1", "Revenue was $100 million.")], as_of=AS_OF
        )
    assert excinfo.value.code == "UNKNOWN_CONTEXT_ITEM"


def test_quote_that_is_not_a_span_of_the_cited_item_is_a_contract_violation() -> None:
    provider = StubProvider(
        {
            "claims": [
                {
                    "text": "Revenue tripled.",
                    "citations": [{"item_id": "item-1", "quote": "Revenue tripled"}],
                    "numeric": None,
                }
            ],
            "abstain": None,
        }
    )
    with pytest.raises(GenerationContractError) as excinfo:
        StructuredClaimGenerator(provider).generate(
            "q", [_ctx("item-1", "Revenue was $100 million.")], as_of=AS_OF
        )
    assert excinfo.value.code == "QUOTE_NOT_IN_CONTEXT_ITEM"


@pytest.mark.parametrize(
    "parsed",
    [
        {"claims": [{"text": "x"}], "abstain": None},  # citations missing
        {"claims": [{"text": "", "citations": [], "numeric": None}], "abstain": None},
        {"claims": [], "abstain": None, "extra": 1},  # unknown member
        {"claims": "not-an-array", "abstain": None},
        {"abstain": None},  # claims missing
    ],
)
def test_schema_invalid_output_fails_closed(parsed: dict[str, Any]) -> None:
    with pytest.raises(GenerationContractError) as excinfo:
        StructuredClaimGenerator(StubProvider(parsed)).generate(
            "q", [_ctx("i", "text")], as_of=AS_OF
        )
    assert excinfo.value.code == "CLAIMS_OUTPUT_SCHEMA_INVALID"


def test_missing_parsed_object_without_refusal_fails_closed() -> None:
    with pytest.raises(GenerationContractError) as excinfo:
        StructuredClaimGenerator(StubProvider(None)).generate("q", [_ctx("i", "text")], as_of=AS_OF)
    assert excinfo.value.code == "CLAIMS_OUTPUT_MISSING"


def test_contract_error_never_echoes_model_text() -> None:
    provider = StubProvider(
        {
            "claims": [
                {
                    "text": "CONFIDENTIAL FABRICATION",
                    "citations": [{"item_id": "ghost", "quote": "CONFIDENTIAL FABRICATION"}],
                    "numeric": None,
                }
            ],
            "abstain": None,
        }
    )
    with pytest.raises(GenerationContractError) as excinfo:
        StructuredClaimGenerator(provider).generate("q", [_ctx("item-1", "Revenue.")], as_of=AS_OF)
    assert "CONFIDENTIAL" not in str(excinfo.value)


def test_explicit_abstain_yields_no_claims_and_records_the_reason() -> None:
    provider = StubProvider({"claims": [], "abstain": {"reason": "context does not answer"}})
    result = StructuredClaimGenerator(provider).generate("q", [_ctx("i", "text")], as_of=AS_OF)
    assert result.claims == ()
    assert result.abstained is True
    assert result.abstain_reason == "context does not answer"
    assert result.refused is False


# --- mock provider ---------------------------------------------------------
def test_mock_provider_emits_schema_valid_claims_from_the_context_block() -> None:
    gen = StructuredClaimGenerator(MockStructuredLLMProvider())
    context = [
        _ctx("11111111-1111-4111-8111-111111111111", "Revenue was $100 million."),
        _ctx(
            "22222222-2222-4222-8222-222222222222",
            "Net income was $28 million.",
            numeric=NumericTuple(Decimal("28"), "USD", "FY2026-Q2", 6),
        ),
    ]
    result = gen.generate("What was revenue?", context, as_of=AS_OF)

    assert not result.refused
    assert result.provider == "mock"
    assert [c.ord for c in result.claims] == [0, 1]
    for claim, item in zip(result.claims, context, strict=True):
        assert claim.text == item.text
        assert claim.citations[0].item_id == item.item_id
        assert claim.citations[0].source_span_id == item.source_span_id
        assert claim.confidence is None
    # The numeric marker rendered into the prompt round-trips back onto the claim.
    assert result.claims[0].numeric is None
    assert result.claims[1].numeric == context[1].numeric


def test_mock_provider_is_deterministic() -> None:
    gen = StructuredClaimGenerator(MockStructuredLLMProvider())
    context = [_ctx("item-1", "Revenue was $100 million.")]
    first = gen.generate("q", context, as_of=AS_OF)
    second = gen.generate("q", context, as_of=AS_OF)
    assert first.claims == second.claims


def test_refusal_yields_no_claims_and_records_usage() -> None:
    # Refusal is configured on the provider; no question or context text can
    # trigger it, so an untrusted turn cannot fake an abstention.
    gen = StructuredClaimGenerator(MockStructuredLLMProvider(refuse=True))
    result = gen.generate("What was revenue?", [_ctx("id", "x")], as_of=AS_OF)
    assert result.refused
    assert result.refusal is not None
    assert result.claims == ()
    assert result.output_tokens >= 1


def test_empty_context_yields_no_claims() -> None:
    gen = StructuredClaimGenerator(MockStructuredLLMProvider())
    result = gen.generate("q", [], as_of=AS_OF)
    assert not result.refused
    assert result.claims == ()


# --- test shim -------------------------------------------------------------
def test_identity_mode_shim_is_opt_in_only() -> None:
    context = [_ctx("item-1", "Revenue was $100 million.")]
    # A provider that returns nothing usable would fail closed in normal mode.
    provider = StubProvider({"claims": [], "abstain": None})
    assert StructuredClaimGenerator(provider).generate("q", context, as_of=AS_OF).claims == ()
    shimmed = StructuredClaimGenerator(provider, identity_mode=True).generate(
        "q", context, as_of=AS_OF
    )
    assert [c.text for c in shimmed.claims] == ["Revenue was $100 million."]
    assert shimmed.claims[0].confidence is None


# --- dataclass invariants --------------------------------------------------
def test_illegal_claim_status_rejected() -> None:
    with pytest.raises(ValueError, match="illegal claim status"):
        GeneratedClaim(ord=0, text="x", status="bogus", citations=())


def test_illegal_citation_status_rejected() -> None:
    with pytest.raises(ValueError, match="illegal citation status"):
        GeneratedClaim(
            ord=0,
            text="x",
            status="supported",
            citations=(ClaimCitation(item_id="i", source_span_id="s", status="bogus"),),
        )


def test_numeric_tuple_sign_is_derived() -> None:
    assert NumericTuple(Decimal("1.5"), "USD", "FY2025", 6).sign == 1
    assert NumericTuple(Decimal("-1.5"), "USD", "FY2025", 6).sign == -1
    assert NumericTuple(Decimal("0"), "USD", "FY2025", 6).sign == 0
