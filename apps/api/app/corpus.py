"""Read-only corpus evidence API (frozen openapi v0.1.0 paths).

GET /v1/entities/{entityId}/documents (point-in-time filtered),
GET /v1/documents/{documentId}, and GET /v1/source-spans/{sourceSpanId}.

Corpus rows are public shared evidence (no org_id, no RLS — see
db/migrations/0002_corpus_core.sql), but every request still authenticates
and resolves tenant membership: evidence reads are available only to
authenticated members, and reads run as the non-privileged fel_app role,
which holds SELECT-only grants on corpus tables. The as_of cutoff is
enforced server-side per spec 10.3: only documents publicly available at or
before the cutoff are returned (boundary-inclusive).

Evidence gate: only documents with at least one successfully PARSED
document version are served. A document whose every ingestion attempt was
quarantined is operational state, not evidence — it is invisible to both
the listing and the by-id endpoint until a parse succeeds.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error

router = APIRouter(prefix="/v1", tags=["corpus"])

# Evidence gate repeated verbatim in every document read below: at least
# one successfully parsed version must exist (quarantined-only documents
# are not evidence). Kept as literal SQL — no string composition — so the
# statements stay static and auditable.
_LIST_DOCUMENTS_SQL = """
    SELECT id, entity_id, form, accession, source_url, content_hash,
           published_at, filed_at, period_start, period_end, ingested_at,
           valid_from, valid_to
    FROM documents
    WHERE entity_id = %s AND EXISTS (
        SELECT 1 FROM document_versions dv
        WHERE dv.document_id = documents.id AND dv.status = 'parsed'
    )
    ORDER BY published_at, accession
"""

_LIST_DOCUMENTS_AS_OF_SQL = """
    SELECT id, entity_id, form, accession, source_url, content_hash,
           published_at, filed_at, period_start, period_end, ingested_at,
           valid_from, valid_to
    FROM documents
    WHERE entity_id = %s AND published_at <= %s AND EXISTS (
        SELECT 1 FROM document_versions dv
        WHERE dv.document_id = documents.id AND dv.status = 'parsed'
    )
    ORDER BY published_at, accession
"""

_GET_DOCUMENT_SQL = """
    SELECT id, entity_id, form, accession, source_url, content_hash,
           published_at, filed_at, period_start, period_end, ingested_at,
           valid_from, valid_to
    FROM documents
    WHERE id = %s AND EXISTS (
        SELECT 1 FROM document_versions dv
        WHERE dv.document_id = documents.id AND dv.status = 'parsed'
    )
"""


def _document_body(row: dict[str, Any]) -> dict[str, Any]:
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


@router.get("/entities/{entity_id}/documents")
def list_entity_documents(
    entity_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    as_of: Annotated[AwareDatetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    """List an entity's documents, point-in-time filtered by ``as_of``."""
    with tenant_connection(ctx) as conn:
        if as_of is not None:
            rows = conn.execute(_LIST_DOCUMENTS_AS_OF_SQL, (entity_id, as_of)).fetchall()
        else:
            rows = conn.execute(_LIST_DOCUMENTS_SQL, (entity_id,)).fetchall()
    return [_document_body(row) for row in rows]


@router.get("/documents/{document_id}")
def get_document(
    document_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Fetch immutable document metadata (contract DocumentMeta)."""
    with tenant_connection(ctx) as conn:
        row = conn.execute(_GET_DOCUMENT_SQL, (document_id,)).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Document not found.")
    return _document_body(row)


@router.get("/source-spans/{source_span_id}")
def get_source_span(
    source_span_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Fetch a stable source span (contract source-span/v1)."""
    with tenant_connection(ctx) as conn:
        row = conn.execute(
            "SELECT document_version_id, section_id, page, start_char, end_char,"
            " text_hash FROM source_spans WHERE id = %s",
            (source_span_id,),
        ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Source span not found.")
    body: dict[str, Any] = {
        "document_version_id": str(row["document_version_id"]),
        "section_id": str(row["section_id"]),
        "start_char": row["start_char"],
        "end_char": row["end_char"],
        "text_hash": row["text_hash"],
    }
    if row["page"] is not None:
        body["page"] = row["page"]
    return body
