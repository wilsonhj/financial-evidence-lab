"""Closed review commands and bounded mutation transport."""

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.errors import api_error
from app.extraction import review
from app.extraction.models import REVIEW_ADAPTER
from app.extraction.routes_runs import Tenant, command_body

router = APIRouter(prefix="/v1", tags=["extraction"])


@router.post("/extractions/review")
async def review_extractions(
    request: Request,
    ctx: Tenant,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> JSONResponse:
    try:
        command = REVIEW_ADAPTER.validate_python(await command_body(request, "review"))
    except ValidationError:
        raise api_error(422, "VALIDATION_ERROR", "Request failed validation.") from None
    result = await run_in_threadpool(
        review.apply,
        ctx,
        command,
        idempotency_key,
        getattr(request.state, "request_id", "unknown"),
    )
    return JSONResponse(result.body, status_code=result.status, headers=result.headers)
