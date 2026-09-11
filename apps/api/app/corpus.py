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

Visibility ruling (integration lead, M1): corpus-read visibility IS "a
successfully parsed version exists". Publish state (corpus_versions /
the single-active pointer) deliberately does NOT gate M1 reads — an
UNPUBLISHED but parsed document is visible through these endpoints.
Corpus-version pinning of reads arrives with M2's corpus-pinned
retrieval; do not add publish gating here before then.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from app.pagination import Order, page_headers, read_page, scope, utc_cutoff
from app.serializers import document_body

router = APIRouter(prefix="/v1", tags=["corpus"])

_LIST_DOCUMENTS_SQL = """
    SELECT d.* FROM documents d
    WHERE d.entity_id = %s
      AND (%s::timestamptz IS NULL OR d.published_at <= %s)
      AND EXISTS (
        SELECT 1 FROM document_versions dv
        WHERE dv.document_id = d.id AND dv.status = 'parsed'
          AND (%s::uuid IS NULL OR EXISTS (
            SELECT 1 FROM corpus_version_documents cvd
            WHERE cvd.document_version_id = dv.id AND cvd.corpus_version_id = %s
          ))
      )
"""


def require_corpus(conn: Any, corpus_version_id: uuid.UUID | None) -> None:
    if corpus_version_id is not None:
        corpus = conn.execute(
            "SELECT status FROM corpus_versions WHERE id = %s", (corpus_version_id,)
        ).fetchone()
        if corpus is None or corpus["status"] not in {"active", "superseded"}:
            raise api_error(
                404, "NOT_FOUND", "Corpus version not found.", {"resource": "corpus_version"}
            )


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


@router.get("/entities/{entity_id}/documents")
def list_entity_documents(
    entity_id: uuid.UUID,
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    as_of: Annotated[AwareDatetime | None, Query()] = None,
    corpus_version_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Complete legacy listing or explicit cutoff/pin-filtered keyset page."""
    as_of = utc_cutoff(as_of) if as_of else None
    with tenant_connection(ctx, snapshot_read=True) as conn:
        require_corpus(conn, corpus_version_id)
        rows, page = read_page(
            conn,
            query=_LIST_DOCUMENTS_SQL,
            params=(entity_id, as_of, as_of, corpus_version_id, corpus_version_id),
            keys=("published_at", "accession", "id"),
            request_scope=scope("documents", ctx.org_id, entity_id, as_of, corpus_version_id),
            limit=limit,
            token=cursor,
            order=order,
        )
    page_headers(response, page)
    return [document_body(row) for row in rows]


@router.get("/document-versions/resolve")
def resolve_document_versions(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    document_version_id: Annotated[list[uuid.UUID], Query(min_length=1, max_length=200)],
    as_of: Annotated[AwareDatetime | None, Query()] = None,
    corpus_version_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[dict[str, str]]:
    """Resolve only requested visible parsed references, never scan the corpus."""
    as_of = utc_cutoff(as_of) if as_of else None
    with tenant_connection(ctx, snapshot_read=True) as conn:
        require_corpus(conn, corpus_version_id)
        rows = conn.execute(
            """
            SELECT dv.id AS document_version_id, dv.document_id
            FROM document_versions dv JOIN documents d ON d.id = dv.document_id
            WHERE dv.id = ANY(%s) AND dv.status = 'parsed'
              AND (%s::timestamptz IS NULL OR d.published_at <= %s)
              AND (%s::uuid IS NULL OR EXISTS (
                SELECT 1 FROM corpus_version_documents cvd
                WHERE cvd.document_version_id = dv.id AND cvd.corpus_version_id = %s))
            ORDER BY dv.id LIMIT 200
        """,
            (list(set(document_version_id)), as_of, as_of, corpus_version_id, corpus_version_id),
        ).fetchall()
    return [{k: str(row[k]) for k in ("document_version_id", "document_id")} for row in rows]


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
    return document_body(row)


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
