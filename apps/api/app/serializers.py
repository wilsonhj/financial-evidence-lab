"""Response serializers shared by more than one router.

``document_body`` used to live in ``corpus.py`` and was imported from there by
``reader.py``; a router reaching into another router for a private helper is a
cycle waiting to happen. The contract shape it emits (DocumentMeta) is
unchanged — this module is a pure move.
"""

from __future__ import annotations

from typing import Any


def document_body(row: dict[str, Any]) -> dict[str, Any]:
    """Contract DocumentMeta; optional temporal fields omitted when unset."""
    body: dict[str, Any] = {
        "id": str(row["id"]),
        "entity_id": str(row["entity_id"]),
        "accession": row["accession"],
        "source_url": row["source_url"],
        "content_hash": row["content_hash"],
        "published_at": row["published_at"].isoformat(),
        "ingested_at": row["ingested_at"].isoformat(),
    }
    if row["form"] is not None:
        body["form"] = row["form"]
    for key in ("filed_at", "valid_from", "valid_to"):
        if row[key] is not None:
            body[key] = row[key].isoformat()
    for key in ("period_start", "period_end"):
        if row[key] is not None:
            body[key] = row[key].isoformat()
    return body
