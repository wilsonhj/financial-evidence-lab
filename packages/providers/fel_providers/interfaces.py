"""Frozen provider protocols. Additions are additive minors per
packages/contracts/VERSIONING.md; the shapes here enter the contract freeze
with the M0-PLATFORM merge (recorded exception in CONTRACTS.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class LLMProvider(Protocol):
    """Text generation. Env (live): FEL_OPENAI_API_KEY."""

    def generate(self, prompt: str, *, max_tokens: int) -> str: ...


@dataclass(frozen=True)
class StructuredGenerationRequest:
    """Typed structured-generation request (ADR-0007 / M3)."""

    schema_name: str
    schema_version: str
    json_schema: dict[str, object]
    messages: list[dict[str, str]]
    max_output_tokens: int
    temperature: float = 0.0


@dataclass(frozen=True)
class StructuredModelResult:
    """Structured model result with usage/refusal metadata (ADR-0007)."""

    provider: str
    model: str
    response_id: str
    parsed: dict[str, object] | None
    refused: bool
    refusal: str | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    raw: dict[str, object]


class StructuredLLMProvider(Protocol):
    """JSON-Schema-constrained generation. Additive to LLMProvider.
    Env (live, later): FEL_OPENAI_API_KEY. M3-CONTRACT ships mock only."""

    def generate_structured(
        self, request: StructuredGenerationRequest
    ) -> StructuredModelResult: ...


class EmbeddingProvider(Protocol):
    """Dense embeddings, <= 512 dimensions per ADR-0002."""

    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class StorageProvider(Protocol):
    """Immutable object storage. Env (live): FEL_SUPABASE_URL / FEL_SUPABASE_SECRET_KEY."""

    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def signed_url(self, key: str, *, expires_seconds: int) -> str: ...


@dataclass(frozen=True)
class MarketBar:
    """Adjusted daily bar; prices are decimal strings end-to-end."""

    day: date
    adjusted_close: Decimal
    volume: int
    dividend: Decimal
    split_factor: Decimal


class MarketDataProvider(Protocol):
    """Adjusted prices + corporate actions (FR-ING-008).
    Env (live): FEL_ALPHAVANTAGE_API_KEY (paid tier per CREDENTIALS.md).
    Implementations must fail closed when adjustments are missing (FOR-005)."""

    def daily_adjusted(self, ticker: str, *, start: date, end: date) -> list[MarketBar]: ...


class SecClient(Protocol):
    """SEC EDGAR public data (no credential; compliant User-Agent required)."""

    def submissions(self, cik: str) -> dict[str, object]: ...
    def fetch_document(self, url: str) -> bytes: ...


class FredClient(Protocol):
    """Vintage-aware FRED series. Env (live): FEL_FRED_API_KEY."""

    def series_vintage(self, series_id: str, *, as_of: datetime) -> list[tuple[date, Decimal]]: ...
