"""Error envelope per contract error/v1 (every non-2xx response)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Build the contract error envelope, optionally with response headers.

    ``headers`` carries protocol metadata that belongs beside the status rather
    than inside the body — ``Retry-After`` on a 429, for instance. The
    application's HTTPException handler copies them onto the JSON response.
    """
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
        headers=headers,
    )


def list_too_large(resource: str, limit: int) -> HTTPException:
    """413 when an omitted list cap would silently drop rows (#191)."""
    return api_error(
        413,
        "LIST_TOO_LARGE",
        "Listing exceeds the default bound; pass an explicit limit to page the newest rows.",
        {"resource": resource, "limit": limit},
    )
