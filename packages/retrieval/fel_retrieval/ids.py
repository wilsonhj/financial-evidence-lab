"""UUIDv5 helpers for retrieval items (ADR-0006 / migration 0003)."""

from __future__ import annotations

import uuid

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://financial-evidence-lab.dev/retrieval")


def source_anchor(
    kind: str,
    *,
    source_span_id: str,
    financial_fact_id: str | None = None,
    table_id: str | None = None,
    table_row_index: int | None = None,
) -> str:
    """Mirror the generated ``retrieval_items.source_anchor`` expression."""
    if kind == "passage":
        return f"span:{source_span_id}"
    if kind == "fact":
        if financial_fact_id is None:
            raise ValueError("fact items require financial_fact_id")
        return f"fact:{financial_fact_id}"
    if kind == "table_row":
        if table_id is None or table_row_index is None:
            raise ValueError("table_row items require table_id and table_row_index")
        return f"table:{table_id}:{table_row_index}"
    raise ValueError(f"unknown retrieval kind: {kind}")


def item_id(
    index_version_id: str,
    kind: str,
    anchor: str,
    content_sha256: str,
) -> str:
    """UUIDv5(index_version_id|kind|source_anchor|content_sha256)."""
    return str(uuid.uuid5(ID_NAMESPACE, f"{index_version_id}|{kind}|{anchor}|{content_sha256}"))
