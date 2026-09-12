"""Authenticated extraction permissions and run transport."""

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.auth import TenantContext
from app.db import tenant_connection
from app.dependencies import get_tenant_context
from app.errors import api_error
from app.extraction import reads, runs, serializers
from app.extraction.models import Action, ExtractionPermissions, ProposalState, RunCreate
from app.pagination import Order

router = APIRouter(prefix="/v1", tags=["extraction"])
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


async def command_body(request: Request, resource_id: UUID | str) -> Any:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise api_error(415, "UNSUPPORTED_MEDIA_TYPE", "Expected application/json.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 1024 * 1024:
            raise reads.too_large(resource_id)
        raw.extend(chunk)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise api_error(422, "VALIDATION_ERROR", "Request failed validation.") from None


@router.post("/workspaces/{workspaceId}/extraction-runs", status_code=202)
async def create_run(
    workspaceId: UUID,
    request: Request,
    ctx: Tenant,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> JSONResponse:
    try:
        body = RunCreate.model_validate(await command_body(request, workspaceId))
    except ValidationError:
        raise api_error(422, "VALIDATION_ERROR", "Request failed validation.") from None
    from starlette.concurrency import run_in_threadpool

    result = await run_in_threadpool(
        runs.create,
        ctx,
        workspaceId,
        body,
        idempotency_key,
        getattr(request.state, "request_id", "unknown"),
    )
    return JSONResponse(result.body, status_code=result.status, headers=result.headers)


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
