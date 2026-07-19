"""Deterministic dense embeddings for retrieval items (M2-011 / T0202).

Embeddings come from an injected ``EmbeddingProvider`` (fel_providers) so the
package stays mock-first with no network and no credentials. The mock provider
is a pure function of content, so identical items always embed identically.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from fel_retrieval.index_version import DIMENSIONS
from fel_retrieval.models import RetrievalItemDraft


class EmbeddingProvider(Protocol):
    """Structural view of ``fel_providers.EmbeddingProvider`` (ADR-0002)."""

    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def embed_drafts(
    provider: EmbeddingProvider,
    drafts: Sequence[RetrievalItemDraft],
    *,
    dimensions: int = DIMENSIONS,
) -> list[tuple[RetrievalItemDraft, list[float]]]:
    """Embed each draft's content; fail closed if a vector is not 512d."""
    if dimensions != DIMENSIONS:
        raise ValueError(f"dimensions must be {DIMENSIONS} (halfvec(512))")
    vectors = provider.embed([draft.content for draft in drafts])
    if len(vectors) != len(drafts):
        raise ValueError("provider returned a different vector count than drafts")
    paired: list[tuple[RetrievalItemDraft, list[float]]] = []
    for draft, vector in zip(drafts, vectors, strict=True):
        if len(vector) != dimensions:
            raise ValueError(
                f"embedding for item {draft.id} has {len(vector)} dims, expected {dimensions}"
            )
        paired.append((draft, [float(component) for component in vector]))
    return paired


def format_halfvec(vector: Sequence[float]) -> str:
    """Render a vector as a pgvector literal for ``%s::halfvec(512)`` casts."""
    return "[" + ",".join(repr(float(component)) for component in vector) + "]"
