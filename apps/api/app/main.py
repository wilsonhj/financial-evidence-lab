"""FastAPI application entrypoint.

M0-PLATFORM wires the platform core: mock-first authentication, tenant-scoped
workspace APIs, request observability, and the contract error envelope. The
application modules for ingestion/retrieval/extraction/modeling/forecasting
are delivered by their milestone packages against the frozen contracts.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.corpus import router as corpus_router
from app.observability import RequestContextMiddleware, configure_logging
from app.reader import router as reader_router
from app.workspaces import router as workspaces_router


class HealthResponse(BaseModel):
    """Liveness contract returned by the health probe."""

    status: str
    service: str
    version: str


configure_logging()
app = FastAPI(title="Financial Evidence Lab API", version=__version__)
app.add_middleware(RequestContextMiddleware)
app.include_router(workspaces_router)
app.include_router(corpus_router)
app.include_router(reader_router)


def _envelope(request: Request, status: int, code: str, message: str, details: Any) -> JSONResponse:
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
        )
    return _envelope(request, exc.status_code, "HTTP_ERROR", str(exc.detail), None)


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
