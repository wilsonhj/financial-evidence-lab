"""Provider interfaces, deterministic mocks, and live adapters (T0010, ADR-0012).

Every external service sits behind one of these narrow protocols
(constitution Principle V). The live adapters (``openai_live``,
``anthropic_live``) sit behind the same protocols and are selected by
environment via :mod:`fel_providers.factory`; the environment variable NAMES
they consume are documented in docs/handoff/CREDENTIALS.md and ADR-0012 —
never values.
"""

from fel_providers.anthropic_live import AnthropicStructuredProvider
from fel_providers.factory import (
    build_embedding_provider,
    build_structured_llm_provider,
)
from fel_providers.interfaces import (
    EmbeddingProvider,
    FredClient,
    LLMProvider,
    MarketBar,
    MarketDataProvider,
    SecClient,
    StorageProvider,
    StructuredGenerationRequest,
    StructuredLLMProvider,
    StructuredModelResult,
)
from fel_providers.live_http import (
    LiveHttpConfig,
    ProviderConfigurationError,
    ProviderError,
    ProviderHttpError,
    ProviderProtocolError,
)
from fel_providers.mocks import (
    MockEmbeddingProvider,
    MockFredClient,
    MockLLMProvider,
    MockMarketDataProvider,
    MockSecClient,
    MockStorageProvider,
    MockStructuredLLMProvider,
)
from fel_providers.openai_live import (
    OpenAIEmbeddingProvider,
    OpenAIStructuredProvider,
)

__all__ = [
    "AnthropicStructuredProvider",
    "EmbeddingProvider",
    "FredClient",
    "LLMProvider",
    "LiveHttpConfig",
    "MarketBar",
    "MarketDataProvider",
    "MockEmbeddingProvider",
    "MockFredClient",
    "MockLLMProvider",
    "MockMarketDataProvider",
    "MockSecClient",
    "MockStorageProvider",
    "MockStructuredLLMProvider",
    "OpenAIEmbeddingProvider",
    "OpenAIStructuredProvider",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderHttpError",
    "ProviderProtocolError",
    "SecClient",
    "StorageProvider",
    "StructuredGenerationRequest",
    "StructuredLLMProvider",
    "StructuredModelResult",
    "build_embedding_provider",
    "build_structured_llm_provider",
]
