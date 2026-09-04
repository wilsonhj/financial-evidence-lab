"""Tenant-scoped database access implementing the frozen RLS pattern:
request paths run as the non-privileged fel_app role with the caller's
claims applied via SET LOCAL request.jwt.claims inside the transaction, so
row-level security actually executes. The service role is reserved for
workers/admin and never used here.

Connections come from a ``psycopg_pool.ConnectionPool`` rather than a fresh
``psycopg.connect()`` per request (#191): a TCP+TLS handshake and a backend
fork per API call is the single largest avoidable latency in the request path,
and an unbounded connect-per-request pattern is also how a burst exhausts
``max_connections``.

Two properties keep pooling safe for tenancy, and both are load-bearing:

* ``SET LOCAL ROLE fel_app`` and ``set_config('request.jwt.claims', …, true)``
  are **transaction-local**. They are applied inside ``conn.transaction()`` and
  are unwound by PostgreSQL at COMMIT/ROLLBACK, so a recycled connection never
  carries one caller's role or claims into the next caller's transaction.
* Pools are keyed by connection string. Tests repoint ``FEL_DATABASE_URL`` at a
  disposable database per module, and a single process-wide pool bound to the
  first URL it ever saw would silently serve the wrong database.

``psycopg_pool`` is imported lazily through ``importlib`` so that (a) a missing
optional dependency produces one clear error at first use instead of an import
error at module import, and (b) static analysis does not require the package to
be installed in every checkout. See ``apps/api/pyproject.toml`` for the
dependency floor.
"""

from __future__ import annotations

import atexit
import importlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.auth import TenantContext
from app.config import settings

# url -> psycopg_pool.ConnectionPool. Guarded by _POOL_LOCK.
_POOLS: dict[str, Any] = {}
_POOL_LOCK = threading.Lock()


def _connection_pool_class() -> Any:
    try:
        module = importlib.import_module("psycopg_pool")
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "psycopg_pool is required for API database access; install"
            " 'psycopg[binary,pool]' (see apps/api/pyproject.toml)."
        ) from exc
    return module.ConnectionPool


def _reset_pooled_connection(conn: Any) -> None:
    """Return a recycled connection to a clean session GUC state.

    ``SET LOCAL`` is unwound at COMMIT. ``RESET ALL`` is defense in depth so a
    leaked session GUC cannot ride into the next tenant's checkout. (``DISCARD
    ALL`` cannot run inside a transaction, and psycopg connections are not
    autocommit by default, so it is the wrong command here.)
    """
    conn.execute("RESET ALL")


def _new_pool(url: str) -> Any:
    cfg = settings()
    pool = _connection_pool_class()(
        url,
        min_size=cfg.db_pool_min,
        max_size=cfg.db_pool_max,
        kwargs={"row_factory": dict_row},
        reset=_reset_pooled_connection,
        # Opened explicitly below: the constructor's implicit open is
        # deprecated in psycopg_pool 3.2+.
        open=False,
    )
    pool.open()
    return pool


def pool_for(url: str) -> Any:
    """Return (creating on first use) the pool for one connection string."""
    with _POOL_LOCK:
        pool = _POOLS.get(url)
        if pool is None:
            pool = _new_pool(url)
            _POOLS[url] = pool
        return pool


def open_pool() -> None:
    """Open the configured pool at application startup (lifespan hook).

    A missing ``FEL_DATABASE_URL`` is not an error here: the mock-first app
    boots without a database and every request path raises its own clear
    error. Pre-opening simply moves pool warm-up off the first request.
    """
    url = settings().database_url
    if url is not None:
        pool_for(url)


def close_pools() -> None:
    """Close every open pool at application shutdown (lifespan hook)."""
    with _POOL_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


atexit.register(close_pools)


@contextmanager
def tenant_connection(
    ctx: TenantContext, *, snapshot_read: bool = False
) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """One transaction with RLS active for the caller's org.

    Composite reads opt into a repeatable-read, read-only transaction so
    every statement observes one PostgreSQL snapshot. Ordinary single-query
    request paths retain the default transaction characteristics.
    """
    url = settings().database_url
    if url is None:
        raise RuntimeError("FEL_DATABASE_URL is not configured")
    claims = json.dumps({"org_id": ctx.org_id, "sub": ctx.user_id, "role": ctx.role})
    with pool_for(url).connection() as pooled:
        conn: psycopg.Connection[dict[str, Any]] = pooled
        with conn.transaction():
            if snapshot_read:
                # Must be the first statement after BEGIN. Values are fixed
                # literals rather than caller-controlled SQL.
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            conn.execute("SET LOCAL ROLE fel_app")
            conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
            yield conn
