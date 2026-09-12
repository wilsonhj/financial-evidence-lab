"""Authenticated extraction permissions and run transport."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.extraction import reads
from app.extraction.models import Action, ExtractionPermissions

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
