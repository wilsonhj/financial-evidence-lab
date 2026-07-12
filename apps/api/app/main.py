"""FastAPI application entrypoint.

M0-SCAFFOLD establishes the process skeleton and a health contract only.
The application modules (identity/workspaces, ingestion, retrieval,
extraction, modeling, forecasting, audit) are delivered by later work
packages against the frozen contracts from M0-CONTRACTS.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__


class HealthResponse(BaseModel):
    """Liveness contract returned by the health probe."""

    status: str
    service: str
    version: str


app = FastAPI(title="Financial Evidence Lab API", version=__version__)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return a static liveness payload for local dev and deployment probes."""
    return HealthResponse(status="ok", service="fel-api", version=__version__)
