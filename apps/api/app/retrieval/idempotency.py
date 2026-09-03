"""Idempotency-Key replay for the retrieval write endpoints.

A stored response body is replayed verbatim, so a retried create bills nothing
and never starts a second run. Keys are scoped by ``(key, org_id, endpoint)``:
one org's key can never replay another's response, and the same key reused on a
different endpoint is a different record.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from app.auth import TenantContext


def _idempotent_replay(
    conn: psycopg.Connection[Any], ctx: TenantContext, endpoint: str, key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT response_body FROM idempotency_keys"
        " WHERE key = %s AND org_id = %s AND endpoint = %s",
        (key, ctx.org_id, endpoint),
    ).fetchone()
    return dict(row["response_body"]) if row else None


def _idempotent_store(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    endpoint: str,
    key: str,
    status: int,
    body: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO idempotency_keys (key, org_id, endpoint, response_status, response_body)"
        " VALUES (%s, %s, %s, %s, %s)",
        (key, ctx.org_id, endpoint, status, json.dumps(body)),
    )
