"""Immutable approved versions and their exact public projection on caller transactions."""

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.auth import TenantContext
from app.errors import api_error
from app.extraction import reads, serializers
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.types import NORMALIZER_VERSION, VALIDATOR_VERSION, ProposalDraft
from fel_workers.extraction.validate.schema import WORKER_EXTENSION_KEYS


def detail(
    conn: psycopg.Connection[dict[str, Any]],
    org: str,
    record_id: str,
    version_id: str | None = None,
) -> dict[str, Any]:
    size = conn.execute(
        "SELECT v.id,octet_length(v.payload::text)+octet_length(v.evidence_manifest::text)+"
        "COALESCE(octet_length(v.validation_context::text),0) AS size "
        "FROM approved_extraction_records r JOIN approved_extraction_versions v "
        "ON v.record_id=r.id AND v.org_id=r.org_id WHERE r.id=%s AND r.org_id=%s "
        "AND v.id=COALESCE(%s::uuid,r.current_version_id)",
        (record_id, org, version_id),
    ).fetchone()
    if size is None:
        raise api_error(404, "NOT_FOUND", "Approved extraction not found.")
    if size["size"] > 1048576:
        raise reads.too_large(record_id)
    row = conn.execute(
        "SELECT v.id AS version_id,v.record_id,v.parent_version_id,v.version,r.kind,r.metric_id,"
        "v.payload,v.evidence_manifest,v.evidence_manifest_hash,v.ontology_version,v.approved_by,"
        "v.created_at,v.approval_reason,v.normalizer_version,v.validator_version,"
        "v.validation_context "
        "FROM approved_extraction_versions v JOIN approved_extraction_records r "
        "ON r.id=v.record_id AND r.org_id=v.org_id WHERE v.id=%s AND v.org_id=%s",
        (size["id"], org),
    ).fetchone()
    assert row is not None
    edges = row.pop("evidence_manifest")
    if len(edges) > 200:
        raise reads.too_large(record_id)
    row["evidence"] = [
        {
            field: edge[field]
            for field in ("source_span_id", "document_version_id", "role", "citation_status")
        }
        for edge in edges
    ]
    for field in ("version_id", "record_id", "parent_version_id", "approved_by"):
        row[field] = str(row[field]) if row[field] is not None else None
    row["created_at"] = row["created_at"].isoformat()
    return row


def create(
    conn: psycopg.Connection[dict[str, Any]],
    ctx: TenantContext,
    workspace_id: str,
    draft: ProposalDraft,
    context: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    record_id = str(uuid4())
    conn.execute(
        "INSERT INTO approved_extraction_records(id,org_id,workspace_id,kind,metric_id,"
        "entity_id) VALUES (%s,%s,%s,%s,%s,%s)",
        (
            record_id,
            ctx.org_id,
            workspace_id,
            draft.kind,
            draft.metric_id,
            draft.payload["entity_id"],
        ),
    )
    body = append_version(conn, ctx, record_id, draft, context, reason, 1, None)
    return {
        "record_id": record_id,
        "version_id": body["version_id"],
        "version": 1,
        "etag": serializers.etag(body),
    }


def append_version(
    conn: psycopg.Connection[dict[str, Any]],
    ctx: TenantContext,
    record_id: str,
    draft: ProposalDraft,
    context: dict[str, Any],
    reason: str,
    version: int,
    parent_id: str | None,
) -> dict[str, Any]:
    version_id = str(uuid4())
    payload = {k: v for k, v in draft.payload.items() if k not in WORKER_EXTENSION_KEYS}
    manifest = sorted(
        draft.evidence,
        key=lambda edge: (edge["source_span_id"], edge["document_version_id"], edge["role"]),
    )
    conn.execute(
        "INSERT INTO approved_extraction_versions(id,org_id,record_id,version,parent_version_id,"
        "origin_proposal_id,payload,comparability_key,evidence_manifest,evidence_manifest_hash,"
        "ontology_version,normalizer_version,validator_version,approved_by,approval_reason,"
        "validation_context) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            version_id,
            ctx.org_id,
            record_id,
            version,
            parent_id,
            draft.id,
            Jsonb(payload),
            Jsonb(draft.comparability_key),
            Jsonb(manifest),
            hash_json(manifest),
            context["source_runs"][0]["ontology_version"],
            NORMALIZER_VERSION,
            VALIDATOR_VERSION,
            ctx.user_id,
            reason,
            Jsonb(context),
        ),
    )
    conn.execute(
        "UPDATE approved_extraction_records SET current_version_id=%s,version=%s "
        "WHERE id=%s AND org_id=%s",
        (version_id, version, record_id, ctx.org_id),
    )
    return detail(conn, ctx.org_id, record_id, version_id)
