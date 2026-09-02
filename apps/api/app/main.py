"""FastAPI application entrypoint.

M0-PLATFORM wires the platform core: mock-first authentication, tenant-scoped
workspace APIs, request observability, and the contract error envelope. The
application modules for ingestion/retrieval/extraction/modeling/forecasting
are delivered by their milestone packages against the frozen contracts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.corpus import router as corpus_router
from app.db import close_pools, open_pool
from app.observability import (
    RequestContextMiddleware,
    configure_error_reporting,
    configure_logging,
)
from app.reader import router as reader_router
from app.retrieval import router as retrieval_router
from app.workspaces import router as workspaces_router


class HealthResponse(BaseModel):
    """Liveness contract returned by the health probe."""

    status: str
    service: str
    version: str


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Own the database connection pool for the process's lifetime (#191)."""
    open_pool()
    try:
        yield
    finally:
        close_pools()


configure_logging()
configure_error_reporting()
app = FastAPI(title="Financial Evidence Lab API", version=__version__, lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
app.include_router(workspaces_router)
app.include_router(corpus_router)
app.include_router(reader_router)
app.include_router(retrieval_router)


def _envelope(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: Any,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return _envelope(
            request,
            exc.status_code,
            str(exc.detail["code"]),
            str(exc.detail.get("message", "")),
            exc.detail.get("details"),
            exc.headers,
        )
    return _envelope(request, exc.status_code, "HTTP_ERROR", str(exc.detail), None, exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _envelope(request, 500, "INTERNAL", "Unexpected server error.", None)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _envelope(request, 422, "VALIDATION_ERROR", "Request failed validation.", exc.errors())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return a static liveness payload for local dev and deployment probes."""
    return HealthResponse(status="ok", service="fel-api", version=__version__)
