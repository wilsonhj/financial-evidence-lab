"""Frozen drafts and rejection diagnostics for the item builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Rejection:
    code: str
    reason: str
    kind: str | None = None
    source_span_id: str | None = None
    table_id: str | None = None
    table_row_index: int | None = None
    financial_fact_id: str | None = None


@dataclass(frozen=True)
class RetrievalItemDraft:
    id: str
    index_version_id: str
    kind: str
    entity_id: str
    document_id: str
    document_version_id: str
    section_id: str
    source_span_id: str
    content: str
    content_sha256: str
    heading_path: tuple[str, ...]
    start_char: int
    end_char: int
    token_count: int
    source_anchor: str
    financial_fact_id: str | None = None
    table_id: str | None = None
    table_row_index: int | None = None
    form: str | None = None
    period: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildResult:
    items: tuple[RetrievalItemDraft, ...]
    rejections: tuple[Rejection, ...]
    chunker_version: str
    config_hash: str

    @property
    def counts(self) -> dict[str, int]:
        by_kind = {"passage": 0, "table_row": 0, "fact": 0}
        for item in self.items:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        return {
            "items": len(self.items),
            "rejections": len(self.rejections),
            **by_kind,
        }
