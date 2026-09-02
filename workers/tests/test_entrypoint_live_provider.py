"""Worker entrypoint binds a live structured provider through the ADR-0012 factory.

No network: a live selection is only constructed, never called.
"""

from __future__ import annotations

import pytest

from fel_workers.__main__ import (
    EXTRACTION_QUEUE,
    build_structured_llm,
    validate_extraction_model_binding,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FEL_LLM_PROVIDER",
        "FEL_ALLOW_MOCK_LLM",
        "FEL_OPENAI_API_KEY",
        "FEL_ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_live_selection_with_credential_binds_live_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_LLM_PROVIDER", "openai")
    monkeypatch.setenv("FEL_OPENAI_API_KEY", "test-key-not-real")
    provider = build_structured_llm(EXTRACTION_QUEUE)
    assert type(provider).__name__ == "OpenAIStructuredProvider"
    validate_extraction_model_binding(EXTRACTION_QUEUE)  # must not raise: a model is configured


def test_live_selection_without_credential_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError) as excinfo:
        build_structured_llm(EXTRACTION_QUEUE)
    assert "FEL_ANTHROPIC_API_KEY" in str(excinfo.value)


def test_naming_the_mock_still_requires_the_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_LLM_PROVIDER", "mock")
    assert build_structured_llm(EXTRACTION_QUEUE) is None
    with pytest.raises(RuntimeError):
        validate_extraction_model_binding(EXTRACTION_QUEUE)


def test_live_selection_is_scoped_to_the_extraction_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_LLM_PROVIDER", "openai")
    monkeypatch.setenv("FEL_OPENAI_API_KEY", "test-key-not-real")
    assert build_structured_llm("ingestion") is None
    with pytest.raises(RuntimeError):
        validate_extraction_model_binding("ingestion")
