"""Error envelope per contract error/v1 (every non-2xx response)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )
