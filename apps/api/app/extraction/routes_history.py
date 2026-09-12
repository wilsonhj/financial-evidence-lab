"""Authenticated bounded extraction history transport."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.extraction import conflicts, reads
from app.extraction.models import ConflictStatus
from app.pagination import Order

router = APIRouter(prefix="/v1", tags=["extraction"])
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


@router.get("/extraction-runs/{runId}/steps")
def list_steps(
    runId: UUID,
    response: Response,
    ctx: Tenant,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = reads.step_page(conn, runId, ctx.org_id, limit, cursor, order)
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/extraction-conflicts/{conflictId}")
def get_conflict(conflictId: UUID, response: Response, ctx: Tenant) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = conflicts.detail(conn, conflictId, ctx.org_id)
    response.headers["ETag"] = body["etag"]
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/workspaces/{workspaceId}/extraction-conflicts")
def list_conflicts(
    workspaceId: UUID,
    response: Response,
    ctx: Tenant,
    status: Annotated[ConflictStatus | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = conflicts.page(conn, workspaceId, ctx.org_id, status, limit, cursor, order)
    response.headers["Cache-Control"] = "no-store"
    return body
