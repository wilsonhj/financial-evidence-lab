"""Build retrieval item drafts from a parsed-corpus view (M2-010 / T0201)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fel_retrieval.chunker import fact_candidates, passage_candidates, table_row_candidates
from fel_retrieval.config import CHUNKER_VERSION, config_hash
from fel_retrieval.hashing import content_sha256, verify_span_slice
from fel_retrieval.ids import item_id, source_anchor
from fel_retrieval.models import BuildResult, Rejection, RetrievalItemDraft

_DEFAULT_CONFIG = {
    "chunker_version": CHUNKER_VERSION,
    "kinds": ["passage", "fact", "table_row"],
}


def _approx_tokens(text: str) -> int:
    # Deterministic stand-in until a tokenizer is authorized (no new deps).
    parts = text.split()
    return len(parts)


def build_items(
    corpus: Mapping[str, Any],
    *,
    index_version_id: str,
    chunker_config: Mapping[str, Any] | None = None,
) -> BuildResult:
    """Return accepted drafts + rejection diagnostics; identical inputs → identical IDs."""
    config = dict(_DEFAULT_CONFIG)
    if chunker_config:
        config.update(dict(chunker_config))
    cfg_hash = config_hash(config)

    entity_id = str(corpus["entity_id"])
    document_id = str(corpus["document_id"])
    document_version_id = str(corpus["document_version_id"])
    canonical_text = str(corpus["canonical_text"])
    form = str(corpus["form"]) if corpus.get("form") is not None else None

    items: list[RetrievalItemDraft] = []
    rejections: list[Rejection] = []

    for passage in passage_candidates(corpus):
        code = verify_span_slice(
            canonical_text,
            start_char=passage.start_char,
            end_char=passage.end_char,
            expected_content=passage.content,
            expected_hash=passage.text_hash,
        )
        if code is not None:
            rejections.append(
                Rejection(
                    code=code,
                    reason=f"passage span {passage.source_span_id} failed re-verify",
                    kind="passage",
                    source_span_id=passage.source_span_id,
                )
            )
            continue
        digest = content_sha256(passage.content)
        anchor = source_anchor("passage", source_span_id=passage.source_span_id)
        items.append(
            RetrievalItemDraft(
                id=item_id(index_version_id, "passage", anchor, digest),
                index_version_id=index_version_id,
                kind="passage",
                entity_id=entity_id,
                document_id=document_id,
                document_version_id=document_version_id,
                section_id=passage.section_id,
                source_span_id=passage.source_span_id,
                content=passage.content,
                content_sha256=digest,
                heading_path=passage.heading_path,
                start_char=passage.start_char,
                end_char=passage.end_char,
                token_count=_approx_tokens(passage.content),
                source_anchor=anchor,
                form=form,
            )
        )

    for fact in fact_candidates(corpus):
        code = verify_span_slice(
            canonical_text,
            start_char=fact.start_char,
            end_char=fact.end_char,
            expected_content=fact.content,
            expected_hash=fact.text_hash,
        )
        if code is not None:
            rejections.append(
                Rejection(
                    code=code,
                    reason=f"fact {fact.financial_fact_id} span failed re-verify",
                    kind="fact",
                    source_span_id=fact.source_span_id,
                    financial_fact_id=fact.financial_fact_id,
                )
            )
            continue
        digest = content_sha256(fact.content)
        anchor = source_anchor(
            "fact",
            source_span_id=fact.source_span_id,
            financial_fact_id=fact.financial_fact_id,
        )
        items.append(
            RetrievalItemDraft(
                id=item_id(index_version_id, "fact", anchor, digest),
                index_version_id=index_version_id,
                kind="fact",
                entity_id=entity_id,
                document_id=document_id,
                document_version_id=document_version_id,
                section_id=fact.section_id,
                source_span_id=fact.source_span_id,
                content=fact.content,
                content_sha256=digest,
                heading_path=fact.heading_path,
                start_char=fact.start_char,
                end_char=fact.end_char,
                token_count=_approx_tokens(fact.content),
                source_anchor=anchor,
                financial_fact_id=fact.financial_fact_id,
                form=form,
                period=fact.period,
            )
        )

    for row in table_row_candidates(corpus):
        if (
            row.source_span_id is None
            or row.start_char is None
            or row.end_char is None
            or row.content is None
            or row.text_hash is None
        ):
            rejections.append(
                Rejection(
                    code="UNANCHORED_TABLE_ROW",
                    reason=f"table {row.table_id} row {row.table_row_index} has no unique span",
                    kind="table_row",
                    table_id=row.table_id,
                    table_row_index=row.table_row_index,
                    source_span_id=row.source_span_id,
                )
            )
            continue
        code = verify_span_slice(
            canonical_text,
            start_char=row.start_char,
            end_char=row.end_char,
            expected_content=row.content,
            expected_hash=row.text_hash,
        )
        if code is not None:
            rejections.append(
                Rejection(
                    code=code,
                    reason=(
                        f"table {row.table_id} row {row.table_row_index} " f"span failed re-verify"
                    ),
                    kind="table_row",
                    table_id=row.table_id,
                    table_row_index=row.table_row_index,
                    source_span_id=row.source_span_id,
                )
            )
            continue
        digest = content_sha256(row.content)
        anchor = source_anchor(
            "table_row",
            source_span_id=row.source_span_id,
            table_id=row.table_id,
            table_row_index=row.table_row_index,
        )
        items.append(
            RetrievalItemDraft(
                id=item_id(index_version_id, "table_row", anchor, digest),
                index_version_id=index_version_id,
                kind="table_row",
                entity_id=entity_id,
                document_id=document_id,
                document_version_id=document_version_id,
                section_id=row.section_id,
                source_span_id=row.source_span_id,
                content=row.content,
                content_sha256=digest,
                heading_path=row.heading_path,
                start_char=row.start_char,
                end_char=row.end_char,
                token_count=_approx_tokens(row.content),
                source_anchor=anchor,
                table_id=row.table_id,
                table_row_index=row.table_row_index,
                form=form,
            )
        )

    items.sort(key=lambda item: (item.kind, item.source_anchor, item.start_char, item.id))
    rejections.sort(
        key=lambda r: (
            r.code,
            r.kind or "",
            r.source_span_id or "",
            r.table_id or "",
            r.table_row_index if r.table_row_index is not None else -1,
            r.financial_fact_id or "",
        )
    )
    return BuildResult(
        items=tuple(items),
        rejections=tuple(rejections),
        chunker_version=CHUNKER_VERSION,
        config_hash=cfg_hash,
    )
