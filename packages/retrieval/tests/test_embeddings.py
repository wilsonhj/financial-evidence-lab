from __future__ import annotations

import pytest

from fel_providers import MockEmbeddingProvider
from fel_retrieval import embed_drafts, format_halfvec
from fel_retrieval.models import RetrievalItemDraft


def _draft(item_id: str, content: str) -> RetrievalItemDraft:
    return RetrievalItemDraft(
        id=item_id,
        index_version_id="idx",
        kind="passage",
        entity_id="e",
        document_id="d",
        document_version_id="dv",
        section_id="sec",
        source_span_id="span",
        content=content,
        content_sha256="sha256:" + ("a" * 64),
        heading_path=(),
        start_char=0,
        end_char=len(content),
        token_count=1,
        source_anchor="span:span",
    )


def test_mock_embeddings_are_deterministic_and_512d() -> None:
    drafts = [_draft("i1", "Revenue rose"), _draft("i2", "Costs fell")]
    first = embed_drafts(MockEmbeddingProvider(512), drafts)
    second = embed_drafts(MockEmbeddingProvider(512), drafts)
    assert [v for _, v in first] == [v for _, v in second]
    assert all(len(v) == 512 for _, v in first)
    # Distinct content yields distinct vectors.
    assert first[0][1] != first[1][1]


def test_embed_drafts_rejects_wrong_dimension() -> None:
    class ShortProvider:
        dimensions = 8

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 8 for _ in texts]

    with pytest.raises(ValueError, match="expected 512"):
        embed_drafts(ShortProvider(), [_draft("i1", "x")])


def test_format_halfvec_literal() -> None:
    assert format_halfvec([1.0, -0.5, 0.0]) == "[1.0,-0.5,0.0]"
