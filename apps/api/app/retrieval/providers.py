"""Pinned identities and provider resolution for a retrieval run.

Every run persists the exact planner / embedding / generation identity it used,
and this module is the only place that turns such a pin back into a live object.
Resolution fails closed: a pin with no wired implementation raises rather than
silently substituting a different provider, so a run records a typed failure
instead of producing evidence attributed to the wrong model.
"""

from __future__ import annotations

import os

from fel_providers import EmbeddingProvider, MockEmbeddingProvider
from fel_providers.anthropic_live import DEFAULT_MODEL as DEFAULT_ANTHROPIC_MODEL
from fel_providers.factory import (
    EMBEDDING_PROVIDER_ENV,
    EMBEDDING_PROVIDERS,
    LLM_PROVIDER_ENV,
    LLM_PROVIDERS,
    build_embedding_provider,
    build_structured_llm_provider,
)
from fel_providers.interfaces import StructuredLLMProvider
from fel_providers.live_http import ProviderConfigurationError
from fel_providers.mocks import MockStructuredLLMProvider
from fel_providers.openai_live import DEFAULT_MODEL as DEFAULT_OPENAI_MODEL

# Planner identity persisted on every query/run. Kept in one place so the query
# guard's run<->query planner-pin agreement always holds.
PLANNER_VERSION = "synonym-planner/v1"

# Generation identity persisted on every run (immutable lineage). The pin is
# read from the environment at request time (ADR-0012 factory knobs) so the
# stored provider/model is exactly what generated the claims. When
# ``FEL_LLM_PROVIDER`` is unset the API keeps the deterministic mock, which is
# the only provider the mock-first stack has ever run; the live cutover (#177)
# sets the knob and the factory's fail-closed rules then govern.
MOCK_GENERATION_PIN = ("mock", "mock-structured-v1")


def generation_pin() -> tuple[str, str]:
    """Return ``(provider, model)`` for the run about to be created."""
    selection = os.environ.get(LLM_PROVIDER_ENV, "").strip().lower()
    if not selection or selection == "mock":
        return MOCK_GENERATION_PIN
    if selection == "anthropic":
        model = os.environ.get("FEL_ANTHROPIC_MODEL", "").strip() or DEFAULT_ANTHROPIC_MODEL
    else:
        model = os.environ.get("FEL_OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL
    return selection, model


class UnsupportedEmbeddingProvider(RuntimeError):
    """The pinned embedding provider has no wired implementation.

    Only the deterministic mock exists today; any other pin fails closed here so
    a run records a typed failure rather than silently using the wrong embedder.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(f"embedding provider {provider!r} (model {model!r}) is not available")
        self.provider = provider
        self.model = model


def _resolve_embedding_provider(provider: str, model: str) -> EmbeddingProvider:
    """Resolve the index's pinned embedder. Makes the persisted pin load-bearing.

    ``('mock', ...)`` -> the 512-dim deterministic mock. No live provider is
    wired yet, so every other pin raises ``UnsupportedEmbeddingProvider`` (caught
    by the pipeline-failure path and recorded as a ``failed`` run).
    """
    if provider == "mock":
        return MockEmbeddingProvider(512)
    if provider in EMBEDDING_PROVIDERS:
        # The index's persisted pin is authoritative: overlay it on the process
        # environment so the factory binds exactly that provider and model, and
        # its own fail-closed rules (credential present, dimensions) apply.
        overlay = {
            **os.environ,
            EMBEDDING_PROVIDER_ENV: provider,
            "FEL_OPENAI_EMBEDDING_MODEL": model,
        }
        try:
            return build_embedding_provider(overlay)
        except ProviderConfigurationError as exc:
            raise UnsupportedEmbeddingProvider(provider, model) from exc
    raise UnsupportedEmbeddingProvider(provider, model)


class UnsupportedGenerationProvider(RuntimeError):
    """The pinned structured-generation provider has no wired implementation.

    Only the deterministic mock exists today; any other pin fails closed so a run
    records a typed failure rather than silently generating with the wrong model.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(f"generation provider {provider!r} (model {model!r}) is not available")
        self.provider = provider
        self.model = model


def _resolve_generation_provider(provider: str, model: str) -> StructuredLLMProvider:
    """Resolve the run's pinned structured-generation provider via the ADR-0012 factory."""
    if provider == "mock":
        return MockStructuredLLMProvider()
    if provider in LLM_PROVIDERS:
        model_env = "FEL_ANTHROPIC_MODEL" if provider == "anthropic" else "FEL_OPENAI_MODEL"
        overlay = {**os.environ, LLM_PROVIDER_ENV: provider, model_env: model}
        try:
            return build_structured_llm_provider(overlay)
        except ProviderConfigurationError as exc:
            raise UnsupportedGenerationProvider(provider, model) from exc
    raise UnsupportedGenerationProvider(provider, model)
