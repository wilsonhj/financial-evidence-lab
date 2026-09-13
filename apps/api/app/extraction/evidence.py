"""Complete source selection and verification through existing canonical byte helpers."""

from datetime import datetime
from typing import Any

import psycopg
from fastapi import HTTPException

from app.errors import api_error
from app.extraction.reads import too_large
from app.reader import _read_canonical_text, _section_body, _span_body


def selected_claim_spans(
    conn: psycopg.Connection[dict[str, Any]], org_id: str, workspace_id: str, claim_ids: list[str]
) -> list[str]:
    if not claim_ids:
        return []
    claims = conn.execute(
        "SELECT c.id FROM claims c JOIN retrieval_runs r ON r.id=c.run_id AND r.org_id=c.org_id "
        "JOIN queries q ON q.id=r.query_id AND q.org_id=r.org_id "
        "WHERE c.id=ANY(%s::uuid[]) AND c.org_id=%s AND q.workspace_id=%s LIMIT 201",
        (claim_ids, org_id, workspace_id),
    ).fetchall()
    if {str(row["id"]) for row in claims} != set(claim_ids):
        raise api_error(404, "NOT_FOUND", "Selected claim not found.")
    edges = conn.execute(
        "SELECT c.claim_id,c.source_span_id FROM citations c JOIN retrieval_items i "
        "ON i.id=c.retrieval_item_id AND i.source_span_id=c.source_span_id "
        "WHERE c.org_id=%s AND c.claim_id=ANY(%s::uuid[]) "
        "ORDER BY c.claim_id,c.source_span_id LIMIT 201",
        (org_id, claim_ids),
    ).fetchall()
    if len(edges) > 200:
        raise too_large(workspace_id)
    if {str(row["claim_id"]) for row in edges} != set(claim_ids):
        raise api_error(422, "VALIDATION_ERROR", "Every selected claim requires source evidence.")
    return sorted({str(row["source_span_id"]) for row in edges})


def verify_spans(
    conn: psycopg.Connection[dict[str, Any]],
    span_ids: list[str],
    entity_id: str,
    corpus_id: str,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    if not span_ids or len(span_ids) > 200:
        raise too_large(corpus_id)
    rows = conn.execute(
        "SELECT s.id,s.document_version_id,s.section_id,s.page,s.start_char,s.end_char,"
        "s.text_hash, "
        "d.published_at,v.canonical_text_key,sec.parent_id,sec.heading,sec.heading_path,sec.ord, "
        "sec.start_char AS section_start,sec.end_char AS section_end "
        "FROM source_spans s JOIN document_versions v ON v.id=s.document_version_id "
        "JOIN documents d ON d.id=v.document_id "
        "JOIN sections sec ON sec.id=s.section_id AND sec.document_version_id=v.id "
        "JOIN corpus_version_documents cv ON cv.document_version_id=v.id "
        "WHERE s.id=ANY(%s::uuid[]) AND d.entity_id=%s AND d.published_at<=%s "
        "AND v.status='parsed' "
        "AND cv.corpus_version_id=%s ORDER BY v.id,s.id LIMIT 201",
        (span_ids, entity_id, cutoff, corpus_id),
    ).fetchall()
    if {str(row["id"]) for row in rows} != set(span_ids):
        raise api_error(
            422, "VALIDATION_ERROR", "Selected evidence is unavailable within the pinned scope."
        )
    total = 0
    previous_version = None
    canonical = ""
    blocks = []
    for row in rows:
        resource_id = str(row["id"])
        try:
            if row["document_version_id"] != previous_version:
                canonical = _read_canonical_text(row["canonical_text_key"], resource_id)
                previous_version = row["document_version_id"]
            section = {
                **row,
                "id": row["section_id"],
                "start_char": row["section_start"],
                "end_char": row["section_end"],
            }
            _section_body(section, canonical)
            _span_body(
                row,
                version_id=str(row["document_version_id"]),
                sections={str(row["section_id"]): section},
                canonical_text=canonical,
            )
        except HTTPException as exc:
            if exc.status_code == 413:
                raise too_large(resource_id) from None
            raise api_error(
                422,
                "VALIDATION_ERROR",
                "Selected evidence failed integrity verification.",
                {"resource_id": resource_id},
            ) from None
        text = canonical[row["start_char"] : row["end_char"]]
        total += len(text.encode("utf-8"))
        if total > 8 * 1024 * 1024:
            raise too_large(resource_id)
        blocks.append(
            {
                "source_span_id": resource_id,
                "document_version_id": str(row["document_version_id"]),
                "text": text,
                "text_hash": row["text_hash"],
                "published_at": row["published_at"].isoformat(),
            }
        )
    return sorted(blocks, key=lambda block: block["source_span_id"])
