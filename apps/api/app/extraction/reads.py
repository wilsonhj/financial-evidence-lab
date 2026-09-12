"""Bounded tenant reads using the caller's transaction and RLS role."""

from typing import Any
from uuid import UUID

import psycopg

from app.errors import api_error


def workspace(
    conn: psycopg.Connection[dict[str, Any]], workspace_id: UUID | str, org_id: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM workspaces WHERE id=%s AND org_id=%s", (workspace_id, org_id)
    ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Workspace not found.")
    return row
