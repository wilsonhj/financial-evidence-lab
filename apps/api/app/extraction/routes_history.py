"""Authenticated bounded extraction history transport."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.extraction import approved, conflicts, events, reads, serializers
from app.extraction.models import ConflictStatus
from app.pagination import Order, read_page, scope

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


@router.get("/approved-extractions/{recordId}")
def get_approved(recordId: UUID, response: Response, ctx: Tenant) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = approved.detail(conn, ctx.org_id, str(recordId))
    response.headers["ETag"] = serializers.etag(body)
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/approved-extractions/{recordId}/versions/{versionId}")
def get_approved_version(
    recordId: UUID, versionId: UUID, response: Response, ctx: Tenant
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = approved.detail(conn, ctx.org_id, str(recordId), str(versionId))
    response.headers["ETag"] = serializers.etag(body)
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/approved-extractions/{recordId}/versions")
def list_approved_versions(
    recordId: UUID,
    response: Response,
    ctx: Tenant,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        approved.detail(conn, ctx.org_id, str(recordId))
        rows, metadata = read_page(
            conn,
            query="SELECT id,version FROM approved_extraction_versions "
            "WHERE org_id=%s AND record_id=%s",
            params=(ctx.org_id, recordId),
            keys=("version", "id"),
            request_scope=scope("approved_versions", ctx.org_id, recordId),
            limit=limit,
            token=cursor,
            order=order,
            force_page=True,
        )
        assert metadata is not None
        body = serializers.page(
            [approved.detail(conn, ctx.org_id, str(recordId), str(row["id"])) for row in rows],
            metadata,
        )
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/extraction-runs/{runId}/event-history")
def list_events(
    runId: UUID,
    response: Response,
    ctx: Tenant,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = events.page(conn, ctx.org_id, str(runId), limit, cursor, order)
    response.headers["Cache-Control"] = "no-store"
    return body
