"""Provider interfaces and deterministic mocks (T0010).

Every external service sits behind one of these narrow protocols
(constitution Principle V). Live implementations are integration-
credentialed work; the environment variable NAMES they will consume are
documented in docs/handoff/CREDENTIALS.md — never values.
"""

from fel_providers.interfaces import (
    EmbeddingProvider,
    FredClient,
    LLMProvider,
    MarketBar,
    MarketDataProvider,
    SecClient,
    StorageProvider,
)
from fel_providers.mocks import (
    MockEmbeddingProvider,
    MockFredClient,
    MockLLMProvider,
    MockMarketDataProvider,
    MockSecClient,
    MockStorageProvider,
)

__all__ = [
    "EmbeddingProvider",
    "FredClient",
    "LLMProvider",
    "MarketBar",
    "MarketDataProvider",
    "MockEmbeddingProvider",
    "MockFredClient",
    "MockLLMProvider",
    "MockMarketDataProvider",
    "MockSecClient",
    "MockStorageProvider",
    "SecClient",
    "StorageProvider",
]
