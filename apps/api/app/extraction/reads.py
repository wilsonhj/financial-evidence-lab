"""Bounded tenant reads using the caller's transaction and RLS role."""

from typing import Any
from uuid import UUID

import psycopg

from app.errors import api_error
from app.extraction import serializers
from app.pagination import Order, read_page, scope


def workspace(
    conn: psycopg.Connection[dict[str, Any]], workspace_id: UUID | str, org_id: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM workspaces WHERE id=%s AND org_id=%s", (workspace_id, org_id)
    ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Workspace not found.")
    return row


RUN_COLUMNS = (
    "id, workspace_id, entity_id, parent_run_id, status, modes, as_of, corpus_version_id, "
    "ontology_version, workflow_version, provider, model, version, created_at, "
    "cancel_requested_at, "
    "max_calls, max_input_tokens, max_output_tokens, max_wall_seconds, max_cost_usd, "
    "calls_used, input_tokens_used, output_tokens_used, cost_usd, (error IS NOT NULL) AS has_error"
)


def run(
    conn: psycopg.Connection[dict[str, Any]], run_id: UUID | str, org_id: str
) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {RUN_COLUMNS} FROM extraction_runs WHERE id=%s AND org_id=%s",
        (run_id, org_id),
    ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Extraction run not found.")
    row["error"] = {} if row.pop("has_error") else None
    return serializers.run(row)


def run_page(
    conn: psycopg.Connection[dict[str, Any]],
    workspace_id: UUID,
    org_id: str,
    limit: int | None,
    cursor: str | None,
    order: Order | None,
) -> dict[str, Any]:
    ws = workspace(conn, workspace_id, org_id)
    rows, metadata = read_page(
        conn,
        query=f"SELECT {RUN_COLUMNS} FROM extraction_runs WHERE workspace_id=%s AND org_id=%s",
        params=(workspace_id, org_id),
        keys=("created_at", "id"),
        request_scope=scope("extraction_runs", org_id, workspace_id, ws["as_of"]),
        limit=limit,
        token=cursor,
        order=order,
        force_page=True,
    )
    for row in rows:
        row["error"] = {} if row.pop("has_error") else None
    assert metadata is not None
    return serializers.page([serializers.run(row) for row in rows], metadata)


def too_large(resource_id: UUID | str) -> Any:
    return api_error(
        413,
        "EXTRACTION_TOO_LARGE",
        "Extraction resource exceeds the read limit.",
        {"resource_id": str(resource_id)},
    )


def proposal(
    conn: psycopg.Connection[dict[str, Any]], proposal_id: UUID | str, org_id: str
) -> dict[str, Any]:
    size = conn.execute(
        "SELECT octet_length(payload::text) AS payload_bytes, "
        "octet_length(validation_summary::text) AS validation_bytes, "
        "octet_length(field_confidences::text) AS confidence_bytes "
        "FROM extraction_proposals WHERE id=%s AND org_id=%s",
        (proposal_id, org_id),
    ).fetchone()
    if size is None:
        raise api_error(404, "NOT_FOUND", "Extraction proposal not found.")
    if max(size.values()) > 1048576:
        raise too_large(proposal_id)
    fields = conn.execute(
        "SELECT k AS key, (payload -> k)::text AS text FROM extraction_proposals, "
        "unnest(%s::text[]) AS k WHERE id=%s AND org_id=%s AND payload ? k",
        (serializers.PUBLIC_FIELDS, proposal_id, org_id),
    ).fetchall()
    if any(len(field["text"]) > 65536 for field in fields):
        raise too_large(proposal_id)
    row = conn.execute(
        "SELECT id,run_id,kind,metric_id,payload::text AS payload_text, record_confidence, "
        "field_confidences, validation_summary,state,review_priority,version "
        "FROM extraction_proposals WHERE id=%s AND org_id=%s",
        (proposal_id, org_id),
    ).fetchone()
    assert row is not None
    row["field_text"] = {field["key"]: field["text"] for field in fields}
    edges = conn.execute(
        "SELECT source_span_id,document_version_id,role,citation_status "
        "FROM extraction_proposal_evidence "
        "WHERE proposal_id=%s AND org_id=%s ORDER BY ordinal,source_span_id,role LIMIT 201",
        (proposal_id, org_id),
    ).fetchall()
    groups = conn.execute(
        "SELECT conflict_id FROM extraction_conflict_members WHERE proposal_id=%s AND org_id=%s "
        "ORDER BY conflict_id LIMIT 101",
        (proposal_id, org_id),
    ).fetchall()
    if len(edges) > 200 or len(groups) > 100:
        raise too_large(proposal_id)
    evidence = [{key: str(value) for key, value in edge.items()} for edge in edges]
    return serializers.proposal(row, evidence, [str(group["conflict_id"]) for group in groups])
