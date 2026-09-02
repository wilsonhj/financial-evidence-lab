"""Provider selection is explicit, defaults to OpenAI, and fails closed (#195)."""

from __future__ import annotations

import pytest

from fel_providers.anthropic_live import AnthropicStructuredProvider
from fel_providers.factory import (
    build_embedding_provider,
    build_structured_llm_provider,
)
from fel_providers.live_http import ProviderConfigurationError
from fel_providers.mocks import MockEmbeddingProvider, MockStructuredLLMProvider
from fel_providers.openai_live import OpenAIEmbeddingProvider, OpenAIStructuredProvider


def test_default_selection_is_openai_per_adr_0002() -> None:
    provider = build_structured_llm_provider({"FEL_OPENAI_API_KEY": "k"})
    assert isinstance(provider, OpenAIStructuredProvider)
    assert build_embedding_provider({"FEL_OPENAI_API_KEY": "k"}).dimensions == 512


def test_anthropic_selection() -> None:
    provider = build_structured_llm_provider(
        {"FEL_LLM_PROVIDER": "anthropic", "FEL_ANTHROPIC_API_KEY": "k"}
    )
    assert isinstance(provider, AnthropicStructuredProvider)
    assert provider.model == "claude-opus-4-8"


def test_model_ids_are_configurable() -> None:
    provider = build_structured_llm_provider(
        {
            "FEL_LLM_PROVIDER": "openai",
            "FEL_OPENAI_API_KEY": "k",
            "FEL_OPENAI_MODEL": "gpt-4.1-mini",
        }
    )
    assert isinstance(provider, OpenAIStructuredProvider)
    assert provider.model == "gpt-4.1-mini"
    embeddings = build_embedding_provider(
        {"FEL_OPENAI_API_KEY": "k", "FEL_OPENAI_EMBEDDING_MODEL": "text-embedding-3-large"}
    )
    assert isinstance(embeddings, OpenAIEmbeddingProvider)
    assert embeddings.model == "text-embedding-3-large"


def test_missing_key_fails_closed() -> None:
    with pytest.raises(ProviderConfigurationError, match="FEL_OPENAI_API_KEY"):
        build_structured_llm_provider({})
    with pytest.raises(ProviderConfigurationError, match="FEL_ANTHROPIC_API_KEY"):
        build_structured_llm_provider({"FEL_LLM_PROVIDER": "anthropic"})
    with pytest.raises(ProviderConfigurationError, match="FEL_OPENAI_API_KEY"):
        build_embedding_provider({})


def test_mock_requires_the_existing_explicit_opt_in() -> None:
    with pytest.raises(ProviderConfigurationError, match="FEL_ALLOW_MOCK_LLM"):
        build_structured_llm_provider({"FEL_LLM_PROVIDER": "mock"})
    provider = build_structured_llm_provider(
        {"FEL_LLM_PROVIDER": "mock", "FEL_ALLOW_MOCK_LLM": "1"}
    )
    assert isinstance(provider, MockStructuredLLMProvider)

    with pytest.raises(ProviderConfigurationError, match="FEL_ALLOW_MOCK_LLM"):
        build_embedding_provider({"FEL_EMBEDDING_PROVIDER": "mock"})
    embeddings = build_embedding_provider(
        {"FEL_EMBEDDING_PROVIDER": "mock", "FEL_ALLOW_MOCK_LLM": "on"}
    )
    assert isinstance(embeddings, MockEmbeddingProvider)


def test_falsy_opt_in_spellings_are_rejected_not_treated_as_unset() -> None:
    # Mirrors fel_workers.__main__._read_mode_flag: the way to unset a mode is
    # to remove the variable, never to write 0/false.
    for value in ("0", "false", "ture"):
        with pytest.raises(ProviderConfigurationError, match="FEL_ALLOW_MOCK_LLM"):
            build_structured_llm_provider({"FEL_LLM_PROVIDER": "mock", "FEL_ALLOW_MOCK_LLM": value})


def test_unknown_selection_is_rejected() -> None:
    with pytest.raises(ProviderConfigurationError, match="FEL_LLM_PROVIDER"):
        build_structured_llm_provider({"FEL_LLM_PROVIDER": "gemini"})
    # Anthropic has no embeddings endpoint, so it is not a legal embedding value.
    with pytest.raises(ProviderConfigurationError, match="FEL_EMBEDDING_PROVIDER"):
        build_embedding_provider({"FEL_EMBEDDING_PROVIDER": "anthropic"})


def test_bad_numeric_configuration_is_rejected() -> None:
    with pytest.raises(ProviderConfigurationError, match="FEL_LLM_TIMEOUT_SECONDS"):
        build_structured_llm_provider(
            {"FEL_OPENAI_API_KEY": "k", "FEL_LLM_TIMEOUT_SECONDS": "soon"}
        )
    with pytest.raises(ProviderConfigurationError, match="FEL_LLM_MAX_RETRIES"):
        build_structured_llm_provider({"FEL_OPENAI_API_KEY": "k", "FEL_LLM_MAX_RETRIES": "many"})
    with pytest.raises(ProviderConfigurationError, match="FEL_LLM_INPUT_USD_PER_MTOK"):
        build_structured_llm_provider(
            {"FEL_OPENAI_API_KEY": "k", "FEL_LLM_INPUT_USD_PER_MTOK": "cheap"}
        )


def test_chat_completions_fallback_is_opt_in() -> None:
    default = build_structured_llm_provider({"FEL_OPENAI_API_KEY": "k"})
    assert isinstance(default, OpenAIStructuredProvider)
    assert default._use_chat_completions is False
    fallback = build_structured_llm_provider(
        {"FEL_OPENAI_API_KEY": "k", "FEL_OPENAI_USE_CHAT_COMPLETIONS": "yes"}
    )
    assert isinstance(fallback, OpenAIStructuredProvider)
    assert fallback._use_chat_completions is True


def test_configuration_errors_never_echo_the_key_value() -> None:
    with pytest.raises(ProviderConfigurationError) as excinfo:
        build_structured_llm_provider(
            {"FEL_OPENAI_API_KEY": "sk-secret-value", "FEL_LLM_MAX_RETRIES": "many"}
        )
    assert "sk-secret-value" not in str(excinfo.value)
