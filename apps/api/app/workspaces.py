"""Workspace API (contract openapi v0.1.0): create/list/get/patch with
Idempotency-Key replay, ETag optimistic concurrency, and audit events."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from psycopg import sql
from pydantic import BaseModel, Field

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from app.observability import record_audit_event

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1)
    entity_id: uuid.UUID
    base_currency: str = Field(pattern="^[A-Z]{3}$")
    fiscal_calendar: str
    as_of: str  # RFC3339; validated by Postgres timestamptz on insert


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    as_of: str | None = None
    active_scenario_id: uuid.UUID | None = None


def _row_to_body(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "org_id": str(row["org_id"]),
        "name": row["name"],
        "entity_id": str(row["entity_id"]),
        "base_currency": row["base_currency"],
        "fiscal_calendar": row["fiscal_calendar"],
        "as_of": row["as_of"].isoformat(),
        "active_scenario_id": (
            str(row["active_scenario_id"]) if row["active_scenario_id"] else None
        ),
        "version": row["version"],
        "created_at": row["created_at"].isoformat(),
    }


@router.post("", status_code=201)
def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)],
) -> dict[str, Any]:
    if ctx.role not in ("owner", "editor"):
        raise api_error(403, "FORBIDDEN", "Role may not create workspaces.")
    with tenant_connection(ctx) as conn:
        replay = conn.execute(
            "SELECT response_status, response_body FROM idempotency_keys"
            " WHERE key = %s AND org_id = %s AND endpoint = %s",
            (idempotency_key, ctx.org_id, "POST /v1/workspaces"),
        ).fetchone()
        if replay:
            response.status_code = replay["response_status"]
            return dict(replay["response_body"])
        workspace_id = uuid.uuid4()
        row = conn.execute(
            """
            INSERT INTO workspaces
                (id, org_id, name, entity_id, base_currency, fiscal_calendar, as_of)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                workspace_id,
                ctx.org_id,
                body.name,
                body.entity_id,
                body.base_currency,
                body.fiscal_calendar,
                body.as_of,
            ),
        ).fetchone()
        if row is None:
            raise api_error(500, "INTERNAL", "Insert returned no row.")
        payload = _row_to_body(row)
        conn.execute(
            "INSERT INTO idempotency_keys (key, org_id, endpoint, response_status, response_body)"
            " VALUES (%s, %s, %s, %s, %s)",
            (idempotency_key, ctx.org_id, "POST /v1/workspaces", 201, json.dumps(payload)),
        )
        record_audit_event(
            conn,
            ctx,
            getattr(request.state, "request_id", "unknown"),
            "workspace.created",
            "workspace",
            str(workspace_id),
            {"name": body.name},
        )
    response.headers["ETag"] = f'"{payload["version"]}"'
    return payload


@router.get("")
def list_workspaces(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[dict[str, Any]]:
    with tenant_connection(ctx) as conn:
        rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at").fetchall()
    return [_row_to_body(r) for r in rows]


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: uuid.UUID,
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    with tenant_connection(ctx) as conn:
        row = conn.execute("SELECT * FROM workspaces WHERE id = %s", (workspace_id,)).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Workspace not found.")
    response.headers["ETag"] = f'"{row["version"]}"'
    return _row_to_body(row)


@router.patch("/{workspace_id}")
def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    request: Request,
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    if_match: Annotated[str, Header(alias="If-Match")],
) -> dict[str, Any]:
    if ctx.role not in ("owner", "editor"):
        raise api_error(403, "FORBIDDEN", "Role may not modify workspaces.")
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise api_error(400, "EMPTY_UPDATE", "At least one field is required.")
    expected_version = if_match.strip().strip('"')
    if not expected_version.isdigit():
        raise api_error(400, "BAD_PRECONDITION", "If-Match must be a version ETag.")
    # Column identifiers come from the pydantic model's fixed field set and
    # are composed with psycopg.sql, never interpolated as text.
    statement = sql.SQL(
        "UPDATE workspaces SET {sets}, version = version + 1"
        " WHERE id = %s AND version = %s RETURNING *"
    ).format(
        sets=sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes)
    )
    with tenant_connection(ctx) as conn:
        row = conn.execute(
            statement, (*changes.values(), workspace_id, int(expected_version))
        ).fetchone()
        if row is None:
            exists = conn.execute(
                "SELECT 1 FROM workspaces WHERE id = %s", (workspace_id,)
            ).fetchone()
            if exists:
                raise api_error(412, "PRECONDITION_FAILED", "Workspace version changed.")
            raise api_error(404, "NOT_FOUND", "Workspace not found.")
        record_audit_event(
            conn,
            ctx,
            getattr(request.state, "request_id", "unknown"),
            "workspace.updated",
            "workspace",
            str(workspace_id),
            {"fields": sorted(changes)},
        )
    response.headers["ETag"] = f'"{row["version"]}"'
    return _row_to_body(row)
