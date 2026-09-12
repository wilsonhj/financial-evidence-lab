"""Authenticated extraction permissions and run transport."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.extraction import reads, serializers
from app.extraction.models import Action, ExtractionPermissions, ProposalState
from app.pagination import Order

router = APIRouter(prefix="/v1", tags=["extraction"])
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


@router.get("/workspaces/{workspaceId}/extraction-permissions")
def extraction_permissions(
    workspaceId: UUID, response: Response, ctx: Tenant
) -> ExtractionPermissions:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        reads.workspace(conn, workspaceId, ctx.org_id)
    actions: list[Action] = []
    if ctx.role in ("owner", "editor"):
        actions = ["create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"]
    elif ctx.role == "reviewer":
        actions = ["accept", "edit", "reject", "merge", "correct"]
    response.headers["Cache-Control"] = "no-store"
    return ExtractionPermissions(workspace_id=workspaceId, allowed_actions=actions)


@router.get("/workspaces/{workspaceId}/extraction-runs")
def list_runs(
    workspaceId: UUID,
    response: Response,
    ctx: Tenant,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = reads.run_page(conn, workspaceId, ctx.org_id, limit, cursor, order)
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/extraction-runs/{runId}")
def get_run(runId: UUID, response: Response, ctx: Tenant) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = reads.run(conn, runId, ctx.org_id)
    response.headers["ETag"] = serializers.etag(body)
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/extractions/{extractionId}")
def get_proposal(extractionId: UUID, response: Response, ctx: Tenant) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = reads.proposal(conn, extractionId, ctx.org_id)
    response.headers["ETag"] = serializers.etag(body)
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/workspaces/{workspaceId}/extractions")
def list_proposals(
    workspaceId: UUID,
    response: Response,
    ctx: Tenant,
    state: Annotated[ProposalState | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    order: Annotated[Order | None, Query()] = None,
) -> dict[str, Any]:
    with tenant_connection(ctx, snapshot_read=True) as conn:
        body = reads.proposal_page(conn, workspaceId, ctx.org_id, state, limit, cursor, order)
    response.headers["Cache-Control"] = "no-store"
    return body
