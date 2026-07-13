"""Tenant-scoped database access implementing the frozen RLS pattern:
request paths run as the non-privileged fel_app role with the caller's
claims applied via SET LOCAL request.jwt.claims inside the transaction, so
row-level security actually executes. The service role is reserved for
workers/admin and never used here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.auth import TenantContext
from app.config import settings


@contextmanager
def tenant_connection(ctx: TenantContext) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """One transaction with RLS active for the caller's org."""
    url = settings().database_url
    if url is None:
        raise RuntimeError("FEL_DATABASE_URL is not configured")
    claims = json.dumps({"org_id": ctx.org_id, "sub": ctx.user_id, "role": ctx.role})
    with psycopg.connect(url, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL ROLE fel_app")
            conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
            yield conn
