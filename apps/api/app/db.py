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
from psycopg.rows import dict_row, tuple_row

from app.auth import TenantContext
from app.config import settings

# pool key -> psycopg_pool.ConnectionPool. Guarded by _POOL_LOCK.
#
# The key is the connection string for tenant pools and the connection string
# plus ``_CORPUS_POOL_SUFFIX`` for corpus-read pools. Two pools over one URL are
# deliberate: they bind different row factories (dict_row vs tuple_row), and a
# single pool would hand a lane the wrong row shape.
_POOLS: dict[str, Any] = {}
_POOL_LOCK = threading.Lock()
_CORPUS_POOL_SUFFIX = "#corpus-read"


def _connection_pool_class() -> Any:
    try:
        module = importlib.import_module("psycopg_pool")
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "psycopg_pool is required for API database access; install"
            " 'psycopg[binary,pool]' (see apps/api/pyproject.toml)."
        ) from exc
    return module.ConnectionPool


def _new_pool(url: str, *, row_factory: Any) -> Any:
    cfg = settings()
    pool = _connection_pool_class()(
        url,
        min_size=cfg.db_pool_min,
        max_size=cfg.db_pool_max,
        kwargs={"row_factory": row_factory},
        # Opened explicitly below: the constructor's implicit open is
        # deprecated in psycopg_pool 3.2+.
        open=False,
    )
    pool.open()
    return pool


def _pool(key: str, url: str, row_factory: Any) -> Any:
    with _POOL_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = _new_pool(url, row_factory=row_factory)
            _POOLS[key] = pool
        return pool


def pool_for(url: str) -> Any:
    """Return (creating on first use) the tenant pool for one connection string."""
    return _pool(url, url, dict_row)


def corpus_pool_for(url: str) -> Any:
    """Return (creating on first use) the tuple-row corpus-read pool for one URL."""
    return _pool(url + _CORPUS_POOL_SUFFIX, url, tuple_row)


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


@contextmanager
def corpus_read_connection(
    *, statement_timeout: str
) -> Iterator[psycopg.Connection[tuple[Any, ...]]]:
    """One pooled, tuple-row connection over the public corpus.

    Corpus/retrieval tables carry no org_id and no RLS by design (0002/0003), so
    a plain read connection observes exactly what the pinned lanes filter to;
    all org-scoped work stays on the RLS-bound ``tenant_connection``. The row
    factory is ``tuple_row`` because the lane SQL consumes positional rows.

    Retrieval lanes run concurrently in threads and a psycopg connection is not
    thread-safe, so each lane holds its own connection for the whole of its call
    — the pool hands out one per lane and takes it back at the end. This
    replaces a raw ``psycopg.connect()`` per lane call (#137): a TCP handshake
    and a backend fork per lane, four lanes per run, was pure request latency,
    and an unbounded connect-per-lane pattern is also how a burst exhausts
    ``max_connections``.

    ``statement_timeout`` is applied transaction-locally (``true``) rather than
    for the session: a pooled connection is reused, and a session-scoped GUC
    would leak one caller's timeout onto the next lane to borrow it.
    """
    url = settings().database_url
    if url is None:
        raise RuntimeError("FEL_DATABASE_URL is not configured")
    with corpus_pool_for(url).connection() as pooled:
        conn: psycopg.Connection[tuple[Any, ...]] = pooled
        conn.execute("SELECT set_config('statement_timeout', %s, true)", (statement_timeout,))
        yield conn
