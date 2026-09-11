"""Composite version-pinned evidence reader (ADR-0005).

The endpoint assembles one cutoff-safe database snapshot, selects exactly one
parsed version per visible filing, and verifies canonical section/span
provenance before returning it. A corrupt or unavailable canonical object is
an integrity failure; the API never serves unverifiable evidence.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query
from psycopg import Connection
from pydantic import AwareDatetime

from app.auth import TenantContext
from app.config import settings
from app.corpus import require_corpus
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from app.pagination import Order, decode_cursor, read_page, scope, utc_cutoff
from app.serializers import document_body

router = APIRouter(prefix="/v1", tags=["corpus"])

_TARGET_DOCUMENT_SQL = """
    SELECT id, entity_id, form, accession, source_url, content_hash,
           published_at, filed_at, period_start, period_end, ingested_at,
           valid_from, valid_to
    FROM documents
    WHERE id = %s AND published_at <= %s
"""

# Eligibility and one selected version per sibling precede the page LIMIT.
_SIBLING_DOCUMENTS_SQL = """
    SELECT d.*, selected.id AS selected_id, selected.canonical_text_key
    FROM documents d CROSS JOIN LATERAL (
        SELECT dv.id, dv.canonical_text_key FROM document_versions dv
        WHERE dv.document_id = d.id AND dv.status = 'parsed'
        ORDER BY dv.created_at DESC, dv.parser_version COLLATE "C" DESC,
                 dv.normalizer_version COLLATE "C" DESC, dv.id DESC LIMIT 1
    ) selected
    WHERE d.entity_id = %s AND d.id <> %s AND d.published_at <= %s
"""
_PINNED_SIBLINGS_SQL = """
    SELECT d.*, selected.version_ids, selected.canonical_keys
    FROM documents d CROSS JOIN LATERAL (
        SELECT array_agg(v.id) AS version_ids, array_agg(v.canonical_text_key) AS canonical_keys
        FROM (
            SELECT dv.id, dv.canonical_text_key FROM corpus_version_documents cvd
            JOIN document_versions dv ON dv.id = cvd.document_version_id
            WHERE cvd.corpus_version_id = %s AND dv.document_id = d.id AND dv.status = 'parsed'
            ORDER BY dv.id LIMIT 2
        ) v
    ) selected
    WHERE d.entity_id = %s AND d.id <> %s AND d.published_at <= %s
      AND cardinality(selected.version_ids) > 0
"""

MAX_SECTIONS = 2000
MAX_SPANS = 10000
MAX_FACTS = 10000
MAX_CANONICAL_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_VERIFIED_BYTES = 32 * 1024 * 1024

_LATEST_PARSED_SQL = """
    SELECT id, document_id, parser_version, normalizer_version,
           canonical_text_key, created_at
    FROM document_versions
    WHERE document_id = %s AND status = 'parsed'
    ORDER BY created_at DESC,
             parser_version COLLATE "C" DESC,
             normalizer_version COLLATE "C" DESC,
             id DESC
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
    ORDER BY dv.id
    LIMIT 2
"""

_SECTIONS_SQL = """
    SELECT id, document_version_id, parent_id, heading, heading_path, ord,
           start_char, end_char
    FROM sections
    WHERE document_version_id = %s
    ORDER BY ord, id
    LIMIT 2001
"""

_ALL_SPANS_SQL = """
    SELECT id, document_version_id, section_id, page, start_char, end_char,
           text_hash
    FROM source_spans
    WHERE document_version_id = %s
    ORDER BY start_char, end_char, id
    LIMIT 10001
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
    ORDER BY ss.start_char, ss.end_char, ss.id
    LIMIT 10001
"""

_FACTS_SQL = """
    SELECT id, entity_id, document_version_id, concept, label, value, unit,
           scale, period_type, period_instant, period_start, period_end,
           dimensions, source_span_id, reported_or_derived, confidence,
           duplicate_of, restates
    FROM financial_facts
    WHERE document_version_id = %s
    ORDER BY id
    LIMIT 10001
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


def _too_large(resource: str, kind: str, limit: int) -> Exception:
    return api_error(
        413,
        "READER_TOO_LARGE",
        "Reader evidence exceeds a resource limit.",
        (
            {
                "resource": resource,
                "limit_kind": kind,
                "limit": limit,
                "metadata_url": f"/v1/documents/{resource}",
            }
            if resource != "canonical_object"
            else {"resource": resource, "limit_kind": kind, "limit": limit}
        ),
    )


def _bound(count: int, limit: int, resource: str, kind: str) -> None:
    if count > limit:
        raise _too_large(resource, kind, limit)


def _json_bytes(body: Any, resource: str, budget: int = MAX_RESPONSE_BYTES) -> int:
    total = 0
    for chunk in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(body):
        total += len(chunk.encode("utf-8"))
        _bound(total, budget, resource, "response_bytes")
    return total


def _read_canonical_text(key: str, resource: str = "canonical_object") -> str:
    """Read one immutable canonical object without allowing path traversal."""
    configured_root = settings().storage_dir
    if not configured_root:
        raise _integrity_error("canonical_text_storage_unavailable")
    root = Path(configured_root).resolve()
    candidate = (root / key).resolve()
    if not candidate.is_relative_to(root):
        raise _integrity_error("invalid_canonical_text_key")
    try:
        with candidate.open("rb") as source:
            raw = source.read(MAX_CANONICAL_BYTES + 1)
        _bound(len(raw), MAX_CANONICAL_BYTES, resource, "canonical_bytes")
        return raw.decode("utf-8")
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


def _evidence_rows(
    conn: Connection[dict[str, Any]],
    query: str,
    params: tuple[Any, ...],
    cap: int,
    resource: str,
    kind: str,
    budget: list[int],
) -> list[dict[str, Any]]:
    """Each query already has cap+1; inspect size before transferring text/JSON."""
    from psycopg import sql

    probe = conn.execute(
        sql.SQL(
            "SELECT count(*) AS n, coalesce(sum(octet_length(to_jsonb(t)::text)),0) AS bytes"
            " FROM ({}) t"
        ).format(sql.SQL(query)),
        params,
    ).fetchone()
    probe = cast(dict[str, Any], probe)
    _bound(probe["n"], cap, resource, kind)
    budget[0] += int(probe["bytes"])
    _bound(budget[0], MAX_RESPONSE_BYTES, resource, "metadata_bytes")
    return conn.execute(query, params).fetchall()


def _slice_bytes(
    text: str, rows: list[dict[str, Any]], resource: str, kind: str, limit: int
) -> None:
    # Reject character amplification before any potentially large section slice.
    _bound(sum(max(0, r["end_char"] - r["start_char"]) for r in rows), limit, resource, kind)
    total = 0
    for row in rows:
        for offset in range(max(0, row["start_char"]), min(len(text), row["end_char"]), 65536):
            total += len(text[offset : min(offset + 65536, row["end_char"])].encode())
            _bound(total, limit, resource, kind)


def _build_document_block(
    conn: Connection[dict[str, Any]],
    document_row: dict[str, Any],
    version_row: dict[str, Any],
    *,
    include_sections: bool,
) -> dict[str, Any]:
    version_id = str(version_row["id"])
    entity_id = str(document_row["entity_id"])
    resource = str(document_row["id"])
    metadata_budget = [0]
    section_rows = _evidence_rows(
        conn,
        _SECTIONS_SQL,
        (version_row["id"],),
        MAX_SECTIONS,
        resource,
        "sections",
        metadata_budget,
    )
    span_query = _ALL_SPANS_SQL if include_sections else _REFERENCED_SPANS_SQL
    span_params = (
        (version_row["id"],) if include_sections else (version_row["id"], version_row["id"])
    )
    span_rows = _evidence_rows(
        conn, span_query, span_params, MAX_SPANS, resource, "spans", metadata_budget
    )
    fact_rows = _evidence_rows(
        conn, _FACTS_SQL, (version_row["id"],), MAX_FACTS, resource, "facts", metadata_budget
    )
    canonical_text = _read_canonical_text(version_row["canonical_text_key"], resource)
    _slice_bytes(canonical_text, section_rows, resource, "section_bytes", MAX_RESPONSE_BYTES)
    _slice_bytes(canonical_text, span_rows, resource, "verification_bytes", MAX_VERIFIED_BYTES)
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
    facts = [
        _fact_body(row, version_id=version_id, entity_id=entity_id, span_ids=span_ids)
        for row in fact_rows
    ]
    block: dict[str, Any] = {
        "meta": document_body(document_row),
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
    document_version_id: Annotated[uuid.UUID | None, Query()] = None,
    include_siblings: Annotated[bool, Query()] = True,
    sibling_limit: Annotated[int | None, Query(ge=1, le=20)] = None,
    sibling_cursor: Annotated[str | None, Query(max_length=2048)] = None,
    sibling_order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    """Complete target evidence plus explicitly bounded related evidence."""
    continuation = decode_cursor(sibling_cursor) if sibling_cursor is not None else None
    if continuation and (
        continuation.scope["endpoint"] != "siblings"
        or continuation.scope["org_id"] != str(ctx.org_id)
        or continuation.scope["resource_id"] != str(document_id)
    ):
        raise api_error(422, "INVALID_CURSOR", "Invalid continuation for this request.")
    if continuation:
        # These are untrusted pins, independently checked against visibility below.
        if document_version_id is None:
            document_version_id = uuid.UUID(continuation.scope["target_version_id"])
        if as_of is None:
            as_of = datetime.fromisoformat(continuation.scope["as_of"])
    effective_as_of = utc_cutoff(as_of or datetime.now(UTC))
    with tenant_connection(ctx, snapshot_read=True) as conn:
        require_corpus(conn, corpus_version_id)
        target = conn.execute(_TARGET_DOCUMENT_SQL, (document_id, effective_as_of)).fetchone()
        if target is None:
            raise _not_found()
        if document_version_id is not None and corpus_version_id is None:
            target_version = conn.execute(
                "SELECT id, canonical_text_key FROM document_versions"
                " WHERE id = %s AND document_id = %s AND status = 'parsed'",
                (document_version_id, document_id),
            ).fetchone()
        else:
            target_version = _select_version(conn, document_id, corpus_version_id)
        if target_version is None or (
            document_version_id is not None
            and str(target_version["id"]) != str(document_version_id)
        ):
            raise _not_found()
        request_scope = scope(
            "siblings",
            ctx.org_id,
            document_id,
            effective_as_of,
            corpus_version_id,
            target_version["id"],
        )
        if sibling_cursor is not None:
            decode_cursor(sibling_cursor, request_scope)
        target_block = _build_document_block(conn, target, target_version, include_sections=True)
        budget = _json_bytes(target_block, str(document_id))
        sibling_blocks: list[dict[str, Any]] = []
        page = None
        if include_siblings:
            params: tuple[Any, ...] = (target["entity_id"], document_id, effective_as_of)
            query = _SIBLING_DOCUMENTS_SQL
            if corpus_version_id is not None:
                query = _PINNED_SIBLINGS_SQL
                params = (corpus_version_id, *params)
            sibling_rows, page = read_page(
                conn,
                query=query,
                params=params,
                keys=("published_at", "accession", "id"),
                request_scope=request_scope,
                limit=sibling_limit,
                token=sibling_cursor,
                order=sibling_order,
                default_limit=10,
                max_limit=20,
                legacy_limit=20,
                force_page=sibling_order is not None,
            )
            for sibling in sibling_rows:
                if corpus_version_id is not None:
                    if len(sibling["version_ids"]) > 1:
                        raise _integrity_error("multiple_pinned_versions")
                    version = {
                        "id": sibling["version_ids"][0],
                        "canonical_text_key": sibling["canonical_keys"][0],
                    }
                else:
                    version = {
                        "id": sibling["selected_id"],
                        "canonical_text_key": sibling["canonical_text_key"],
                    }
                block = _build_document_block(conn, sibling, version, include_sections=False)
                budget += _json_bytes(block, str(sibling["id"]), MAX_RESPONSE_BYTES - budget)
                sibling_blocks.append(block)
        else:
            page = {
                "limit": sibling_limit or 10,
                "returned": 0,
                "complete": False,
                "next_cursor": None,
                "previous_cursor": None,
            }
        _close_fact_links([target_block, *sibling_blocks])
    body = {
        "as_of": effective_as_of.isoformat(),
        "corpus_version_id": str(corpus_version_id) if corpus_version_id else None,
        "selection_policy": "corpus_pinned" if corpus_version_id else "latest_parsed",
        "document": target_block,
        "siblings": sibling_blocks,
    }
    if page is not None:
        body["sibling_page"] = {"scope": "page" if include_siblings else "excluded", **page}
    _json_bytes(body, str(document_id))
    return body
