"""Exercise generation-to-terminal runtime behavior without a database."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

import app.retrieval as retrieval
from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_providers.mocks import MockStructuredLLMProvider
from fel_retrieval.generation import ContextItem


class RecordingWriter:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.usage: dict[str, int] = {}

    def set_status(self, status: str) -> None:
        self.statuses.append(status)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))

    def finish_abstained(self, *, budget_usage: dict[str, int], timings_ms: dict[str, int]) -> None:
        self.statuses.append("abstained")
        self.usage = budget_usage


@pytest.mark.parametrize("response_kind", ["schema", "unknown_citation", "abstain", "refusal"])
def test_generation_rejections_preserve_usage_and_finish_abstained(
    monkeypatch: pytest.MonkeyPatch, response_kind: str
) -> None:
    writer = RecordingWriter()
    persisted_claims: list[Any] = []
    item = ContextItem("item-1", "passage", "Revenue increased.", "span-1", "version-1")

    class Provider(MockStructuredLLMProvider):
        def generate_structured(
            self, request: StructuredGenerationRequest
        ) -> StructuredModelResult:
            result = super().generate_structured(request)
            parsed: dict[str, Any] = {"claims": "invalid", "abstain": None}
            if response_kind == "unknown_citation":
                parsed = {
                    "claims": [
                        {
                            "text": "MODEL_PRIVATE_TEXT",
                            "citations": [{"item_id": "MODEL_PRIVATE_TEXT", "quote": "x"}],
                            "numeric": None,
                        }
                    ],
                    "abstain": None,
                }
            elif response_kind == "abstain":
                parsed = {"claims": [], "abstain": {"reason": "MODEL_PRIVATE_TEXT"}}
            return replace(
                result,
                parsed=parsed,
                refused=response_kind == "refusal",
                input_tokens=17,
                output_tokens=9,
            )

    monkeypatch.setattr(retrieval, "_RunWriter", lambda *a, **kw: writer)
    monkeypatch.setattr(retrieval, "_resolve_generation_provider", lambda *a: Provider())
    monkeypatch.setattr(retrieval, "_lane_query", lambda *a, **kw: None)
    monkeypatch.setattr(retrieval, "execute_lanes", lambda *a: {})
    monkeypatch.setattr(
        retrieval,
        "fuse",
        lambda *a, **kw: SimpleNamespace(
            candidates=[SimpleNamespace(item_id=item.item_id)], decisions=[]
        ),
    )
    monkeypatch.setattr(retrieval, "_persist_candidates", lambda *a, **kw: None)
    monkeypatch.setattr(retrieval, "_load_context_items", lambda *a: [item])
    monkeypatch.setattr(retrieval, "_context_tokens", lambda *a: 3)
    monkeypatch.setattr(
        retrieval, "_persist_claims", lambda *a, **kw: persisted_claims.extend(kw["claims"])
    )
    retrieval._execute_pipeline(
        None,  # type: ignore[arg-type]
        run_id="run-1",
        org_id="org-1",
        plan={
            "effective_as_of": "2026-01-01T00:00:00+00:00",
            "budgets": {"fused_top_k": 1, "context_items": 1},
            "lanes": [],
            "variants": ["What happened to revenue?"],
            "intent": "lookup",
        },
        mode="execute",
        embedding_provider="mock",
        embedding_model="mock-embed-v1",
    )

    assert writer.statuses[-2:] == ["verifying", "abstained"]
    assert writer.usage == {
        "context_items": 1,
        "context_tokens": 3,
        "input_tokens": 17,
        "output_tokens": 9,
    }
    expected_payload = {"reason": "generation_contract_invalid"}
    if response_kind == "schema":
        expected_payload["code"] = "CLAIMS_OUTPUT_SCHEMA_INVALID"
    elif response_kind == "unknown_citation":
        expected_payload["code"] = "UNKNOWN_CONTEXT_ITEM"
    elif response_kind == "abstain":
        expected_payload = {"reason": "model_abstained"}
    else:
        expected_payload = {"reason": "provider_refused"}
    assert writer.events[-1] == ("run_abstained", expected_payload)
    assert "MODEL_PRIVATE_TEXT" not in str(writer.events)
    assert persisted_claims == []
    assert not any(kind == "claim_generated" for kind, _ in writer.events)
