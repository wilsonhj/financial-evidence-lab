"""The API's persisted provider pin resolves through the ADR-0012 factory.

No database and no network: these exercise the pure resolution rules.
"""

from __future__ import annotations

import pytest

from app import retrieval
from fel_providers.mocks import MockEmbeddingProvider, MockStructuredLLMProvider


def test_generation_pin_defaults_to_mock_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_LLM_PROVIDER", raising=False)
    assert retrieval.generation_pin() == retrieval.MOCK_GENERATION_PIN


def test_generation_pin_reads_live_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_LLM_PROVIDER", "openai")
    monkeypatch.setenv("FEL_OPENAI_MODEL", "pinned-model")
    assert retrieval.generation_pin() == ("openai", "pinned-model")


def test_mock_pins_resolve_to_mock_providers() -> None:
    assert isinstance(
        retrieval._resolve_generation_provider("mock", "mock-structured-v1"),
        MockStructuredLLMProvider,
    )
    assert isinstance(
        retrieval._resolve_embedding_provider("mock", "mock-v1"), MockEmbeddingProvider
    )


def test_live_pin_without_credential_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FEL_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(retrieval.UnsupportedGenerationProvider):
        retrieval._resolve_generation_provider("anthropic", "some-model")
    with pytest.raises(retrieval.UnsupportedEmbeddingProvider):
        retrieval._resolve_embedding_provider("openai", "text-embedding-3-small")


def test_unknown_pin_fails_closed() -> None:
    with pytest.raises(retrieval.UnsupportedGenerationProvider):
        retrieval._resolve_generation_provider("someone-else", "x")
    with pytest.raises(retrieval.UnsupportedEmbeddingProvider):
        retrieval._resolve_embedding_provider("someone-else", "x")


def test_live_pin_with_credential_binds_live_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_OPENAI_API_KEY", "test-key-not-real")
    provider = retrieval._resolve_generation_provider("openai", "pinned-model")
    assert type(provider).__name__ == "OpenAIStructuredProvider"
    embedder = retrieval._resolve_embedding_provider("openai", "text-embedding-3-small")
    assert type(embedder).__name__ == "OpenAIEmbeddingProvider"
