"""Request IDs, structured JSON logs, latency metrics, and append-only audit
events (spec section 17.1/18.1 baseline)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import psycopg
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.auth import TenantContext

log = logging.getLogger("fel_api")


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "org_id", "path", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        return json.dumps(entry)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID, times the request, and emits one JSON log line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request failed",
                extra={"request_id": request_id, "path": request.url.path},
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def record_audit_event(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    request_id: str,
    action: str,
    object_type: str,
    object_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append-only; the schema has no update/delete policies."""
    conn.execute(
        """
        INSERT INTO audit_events
            (org_id, actor_user_id, request_id, action, object_type, object_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            ctx.org_id,
            ctx.user_id,
            request_id,
            action,
            object_type,
            object_id,
            json.dumps(payload or {}),
        ),
    )
