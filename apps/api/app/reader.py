"""Composite version-pinned evidence reader (ADR-0005).

The endpoint assembles one cutoff-safe database snapshot, selects exactly one
parsed version per visible filing, and verifies canonical section/span
provenance before returning it. A corrupt or unavailable canonical object is
an integrity failure; the API never serves unverifiable evidence.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from psycopg import Connection
from pydantic import AwareDatetime

from app.auth import TenantContext
from app.config import settings
from app.corpus import _document_body
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error

router = APIRouter(prefix="/v1", tags=["corpus"])

_TARGET_DOCUMENT_SQL = """
    SELECT id, entity_id, form, accession, source_url, content_hash,
           published_at, filed_at, period_start, period_end, ingested_at,
           valid_from, valid_to
    FROM documents
    WHERE id = %s AND published_at <= %s
"""

_SIBLING_DOCUMENTS_SQL = """
    SELECT id, entity_id, form, accession, source_url, content_hash,
           published_at, filed_at, period_start, period_end, ingested_at,
           valid_from, valid_to
    FROM documents
    WHERE entity_id = %s AND id <> %s AND published_at <= %s
    ORDER BY published_at, accession, id::text COLLATE "C"
"""

_LATEST_PARSED_SQL = """
    SELECT id, document_id, parser_version, normalizer_version,
           canonical_text_key, created_at
    FROM document_versions
    WHERE document_id = %s AND status = 'parsed'
    ORDER BY created_at DESC,
             parser_version COLLATE "C" DESC,
             normalizer_version COLLATE "C" DESC,
             id::text COLLATE "C" DESC
    LIMIT 1
"""

_PINNED_PARSED_SQL = """
    SELECT dv.id, dv.document_id, dv.parser_version, dv.normalizer_version,
           dv.canonical_text_key, dv.created_at
    FROM corpus_version_documents cvd
    JOIN document_versions dv ON dv.id = cvd.document_version_id
    WHERE cvd.corpus_version_id = %s
      AND dv.document_id = %s
      AND dv.status = 'parsed'
    ORDER BY dv.id::text COLLATE "C"
    LIMIT 2
"""

_SECTIONS_SQL = """
    SELECT id, document_version_id, parent_id, heading, heading_path, ord,
           start_char, end_char
    FROM sections
    WHERE document_version_id = %s
    ORDER BY ord, id::text COLLATE "C"
"""

_ALL_SPANS_SQL = """
    SELECT id, document_version_id, section_id, page, start_char, end_char,
           text_hash
    FROM source_spans
    WHERE document_version_id = %s
    ORDER BY start_char, end_char, id::text COLLATE "C"
"""

_REFERENCED_SPANS_SQL = """
    SELECT ss.id, ss.document_version_id, ss.section_id, ss.page,
           ss.start_char, ss.end_char, ss.text_hash
    FROM source_spans ss
    WHERE ss.document_version_id = %s
      AND EXISTS (
          SELECT 1
          FROM financial_facts ff
          WHERE ff.document_version_id = %s
            AND ff.source_span_id = ss.id
      )
    ORDER BY ss.start_char, ss.end_char, ss.id::text COLLATE "C"
"""

_FACTS_SQL = """
    SELECT id, entity_id, document_version_id, concept, label, value, unit,
           scale, period_type, period_instant, period_start, period_end,
           dimensions, source_span_id, reported_or_derived, confidence,
           duplicate_of, restates
    FROM financial_facts
    WHERE document_version_id = %s
    ORDER BY id::text COLLATE "C"
"""


def _not_found() -> Exception:
    return api_error(404, "NOT_FOUND", "Document not found.")


def _integrity_error(reason: str) -> Exception:
    return api_error(
        500,
        "INTEGRITY_ERROR",
        "Reader evidence failed integrity validation.",
        {"reason": reason},
    )


def _read_canonical_text(key: str) -> str:
    """Read one immutable canonical object without allowing path traversal."""
    configured_root = settings().storage_dir
    if not configured_root:
        raise _integrity_error("canonical_text_storage_unavailable")
    root = Path(configured_root).resolve()
    candidate = (root / key).resolve()
    if not candidate.is_relative_to(root):
        raise _integrity_error("invalid_canonical_text_key")
    try:
        return candidate.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _integrity_error("canonical_text_unavailable") from exc


def _select_version(
    conn: Connection[dict[str, Any]], document_id: uuid.UUID, corpus_version_id: uuid.UUID | None
) -> dict[str, Any] | None:
    if corpus_version_id is None:
        return conn.execute(_LATEST_PARSED_SQL, (document_id,)).fetchone()
    rows = conn.execute(_PINNED_PARSED_SQL, (corpus_version_id, document_id)).fetchall()
    if len(rows) > 1:
        raise _integrity_error("multiple_pinned_versions")
    return rows[0] if rows else None


def _section_body(row: dict[str, Any], canonical_text: str) -> dict[str, Any]:
    start, end = row["start_char"], row["end_char"]
    if start < 0 or end < start or end > len(canonical_text):
        raise _integrity_error("section_outside_canonical_text")
    body: dict[str, Any] = {
        "id": str(row["id"]),
        "document_version_id": str(row["document_version_id"]),
        "heading": row["heading"],
        "heading_path": list(row["heading_path"]),
        "ord": row["ord"],
        "start_char": start,
        "end_char": end,
        "content": canonical_text[start:end],
    }
    if row["parent_id"] is not None:
        body["parent_id"] = str(row["parent_id"])
    return body


def _span_body(
    row: dict[str, Any],
    *,
    version_id: str,
    sections: dict[str, dict[str, Any]],
    canonical_text: str,
) -> dict[str, Any]:
    section_id = str(row["section_id"])
    section = sections.get(section_id)
    start, end = row["start_char"], row["end_char"]
    if str(row["document_version_id"]) != version_id or section is None:
        raise _integrity_error("span_crosses_selected_version")
    if not (section["start_char"] <= start <= end <= section["end_char"]):
        raise _integrity_error("span_outside_section")
    actual_hash = "sha256:" + hashlib.sha256(canonical_text[start:end].encode()).hexdigest()
    if actual_hash != row["text_hash"]:
        raise _integrity_error("span_hash_mismatch")
    span: dict[str, Any] = {
        "document_version_id": version_id,
        "section_id": section_id,
        "start_char": start,
        "end_char": end,
        "text_hash": row["text_hash"],
    }
    if row["page"] is not None:
        span["page"] = row["page"]
    return {"id": str(row["id"]), "span": span}


def _fact_body(
    row: dict[str, Any], *, version_id: str, entity_id: str, span_ids: set[str]
) -> dict[str, Any]:
    source_span_id = str(row["source_span_id"])
    if str(row["document_version_id"]) != version_id or str(row["entity_id"]) != entity_id:
        raise _integrity_error("fact_crosses_selected_version")
    if source_span_id not in span_ids:
        raise _integrity_error("fact_source_span_missing")
    period: dict[str, Any] = {"type": row["period_type"]}
    if row["period_instant"] is not None:
        period["instant"] = row["period_instant"].isoformat()
    if row["period_start"] is not None:
        period["start"] = row["period_start"].isoformat()
    if row["period_end"] is not None:
        period["end"] = row["period_end"].isoformat()
    fact: dict[str, Any] = {
        "entity_id": entity_id,
        "concept": row["concept"],
        "value": row["value"],
        "unit": row["unit"],
        "scale": row["scale"],
        "period": period,
        "dimensions": dict(row["dimensions"]),
        "source_span_id": source_span_id,
        "reported_or_derived": row["reported_or_derived"],
    }
    if row["label"] is not None:
        fact["label"] = row["label"]
    if row["confidence"] is not None:
        fact["confidence"] = float(row["confidence"])
    body: dict[str, Any] = {
        "id": str(row["id"]),
        "document_version_id": version_id,
        "fact": fact,
    }
    if row["duplicate_of"] is not None:
        body["duplicate_of"] = str(row["duplicate_of"])
    if row["restates"] is not None:
        body["restates"] = str(row["restates"])
    return body


def _build_document_block(
    conn: Connection[dict[str, Any]],
    document_row: dict[str, Any],
    version_row: dict[str, Any],
    *,
    include_sections: bool,
) -> dict[str, Any]:
    version_id = str(version_row["id"])
    entity_id = str(document_row["entity_id"])
    canonical_text = _read_canonical_text(version_row["canonical_text_key"])
    section_rows = conn.execute(_SECTIONS_SQL, (version_row["id"],)).fetchall()
    if any(str(row["document_version_id"]) != version_id for row in section_rows):
        raise _integrity_error("section_crosses_selected_version")
    section_ids = {str(row["id"]) for row in section_rows}
    if any(
        row["parent_id"] is not None and str(row["parent_id"]) not in section_ids
        for row in section_rows
    ):
        raise _integrity_error("section_parent_missing")
    section_bodies = [_section_body(row, canonical_text) for row in section_rows]
    sections_by_id = {section["id"]: section for section in section_bodies}

    if include_sections:
        span_rows = conn.execute(_ALL_SPANS_SQL, (version_row["id"],)).fetchall()
    else:
        span_rows = conn.execute(
            _REFERENCED_SPANS_SQL, (version_row["id"], version_row["id"])
        ).fetchall()
    spans = [
        _span_body(
            row,
            version_id=version_id,
            sections=sections_by_id,
            canonical_text=canonical_text,
        )
        for row in span_rows
    ]
    span_ids = {span["id"] for span in spans}
    fact_rows = conn.execute(_FACTS_SQL, (version_row["id"],)).fetchall()
    facts = [
        _fact_body(row, version_id=version_id, entity_id=entity_id, span_ids=span_ids)
        for row in fact_rows
    ]
    block: dict[str, Any] = {
        "meta": _document_body(document_row),
        "document_version_id": version_id,
        "spans": spans,
        "facts": facts,
    }
    if include_sections:
        block["sections"] = section_bodies
    return block


def _close_fact_links(blocks: list[dict[str, Any]]) -> None:
    """Expose optional duplicate/restatement links only when response-local."""
    fact_ids = {fact["id"] for block in blocks for fact in block["facts"]}
    for block in blocks:
        for fact in block["facts"]:
            for link in ("duplicate_of", "restates"):
                if link in fact and fact[link] not in fact_ids:
                    del fact[link]


@router.get("/documents/{document_id}/reader")
def get_document_reader(
    document_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    as_of: Annotated[AwareDatetime | None, Query()] = None,
    corpus_version_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    """Return one cutoff-safe, version-consistent evidence-reader snapshot."""
    effective_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
    with tenant_connection(ctx, snapshot_read=True) as conn:
        if corpus_version_id is not None:
            corpus = conn.execute(
                "SELECT status FROM corpus_versions WHERE id = %s", (corpus_version_id,)
            ).fetchone()
            if corpus is None or corpus["status"] not in {"active", "superseded"}:
                raise api_error(
                    404,
                    "NOT_FOUND",
                    "Corpus version not found.",
                    {"resource": "corpus_version"},
                )

        target = conn.execute(_TARGET_DOCUMENT_SQL, (document_id, effective_as_of)).fetchone()
        if target is None:
            raise _not_found()
        target_version = _select_version(conn, document_id, corpus_version_id)
        if target_version is None:
            raise _not_found()

        target_block = _build_document_block(conn, target, target_version, include_sections=True)
        sibling_rows = conn.execute(
            _SIBLING_DOCUMENTS_SQL,
            (target["entity_id"], document_id, effective_as_of),
        ).fetchall()
        sibling_blocks: list[dict[str, Any]] = []
        for sibling in sibling_rows:
            sibling_version = _select_version(conn, sibling["id"], corpus_version_id)
            if sibling_version is not None:
                sibling_blocks.append(
                    _build_document_block(conn, sibling, sibling_version, include_sections=False)
                )
        _close_fact_links([target_block, *sibling_blocks])

    return {
        "as_of": effective_as_of.isoformat(),
        "corpus_version_id": str(corpus_version_id) if corpus_version_id else None,
        "selection_policy": "corpus_pinned" if corpus_version_id else "latest_parsed",
        "document": target_block,
        "siblings": sibling_blocks,
    }
