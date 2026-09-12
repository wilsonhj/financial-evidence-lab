"""Complete bounded conflict membership, on the caller's tenant transaction."""

from typing import Any
from uuid import UUID

import psycopg

from app.errors import api_error
from app.extraction import reads, serializers
from app.pagination import Order, read_page, scope


def detail(
    conn: psycopg.Connection[dict[str, Any]], conflict_id: UUID | str, org_id: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id,conflict_key,occurrence_run_id,status,reason_codes FROM extraction_conflicts "
        "WHERE id=%s AND org_id=%s",
        (conflict_id, org_id),
    ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Extraction conflict not found.")
    members = conn.execute(
        "SELECT m.proposal_id,p.version FROM extraction_conflict_members m "
        "JOIN extraction_proposals p ON p.id=m.proposal_id AND p.org_id=m.org_id "
        "WHERE m.conflict_id=%s AND m.org_id=%s ORDER BY m.proposal_id LIMIT 201",
        (conflict_id, org_id),
    ).fetchall()
    if len(members) > 200:
        raise reads.too_large(conflict_id)
    if len(members) < 2:
        raise api_error(
            409, "CONFLICT", "Conflict membership is incomplete.", {"resource_id": str(conflict_id)}
        )
    body = {
        "id": str(row["id"]),
        "conflict_key": row["conflict_key"],
        "occurrence_run_id": str(row["occurrence_run_id"]) if row["occurrence_run_id"] else None,
        "status": row["status"],
        "reason_codes": row["reason_codes"],
        "member_versions": {str(member["proposal_id"]): member["version"] for member in members},
        "resolution": None,
    }
    body["etag"] = serializers.etag(body)
    return body


def page(
    conn: psycopg.Connection[dict[str, Any]],
    workspace_id: UUID,
    org_id: str,
    status: str | None,
    limit: int | None,
    cursor: str | None,
    order: Order | None,
) -> dict[str, Any]:
    ws = reads.workspace(conn, workspace_id, org_id)
    rows, metadata = read_page(
        conn,
        query="SELECT id,created_at FROM extraction_conflicts WHERE workspace_id=%s "
        "AND org_id=%s AND (%s::text IS NULL OR status=%s)",
        params=(workspace_id, org_id, status, status),
        keys=("created_at", "id"),
        request_scope=scope(
            "extraction_conflicts", org_id, workspace_id, ws["as_of"], extraction_filter=status
        ),
        limit=limit,
        token=cursor,
        order=order,
        force_page=True,
    )
    assert metadata is not None
    return serializers.page([detail(conn, row["id"], org_id) for row in rows], metadata)
