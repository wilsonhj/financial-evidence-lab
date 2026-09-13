"""Exact immutable response replay serialized before resource locks."""

import importlib
import importlib.util
import queue
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.db import tenant_connection


def _module():
    assert (
        importlib.util.find_spec("app.extraction.receipts") is not None
    ), "receipt implementation missing"
    return importlib.import_module("app.extraction.receipts")


def _context(tenant):
    return TenantContext(tenant["org"], tenant["user"], "owner")


def test_replay_returns_original_status_body_and_headers(extraction_tenant):
    receipts = _module()
    ctx = _context(extraction_tenant)
    key = str(uuid.uuid4())
    request = {"actor": ctx.user_id, "resource": extraction_tenant["workspace"], "version": '"old"'}
    original = {"id": str(uuid.uuid4()), "version": 1}
    headers = {"ETag": '"original"', "Location": "/v1/extractions/original"}
    with tenant_connection(ctx) as conn:
        assert receipts.begin(conn, ctx.org_id, "extraction.correct", key, request) is None
        receipts.save(conn, ctx.org_id, "extraction.correct", key, request, 201, original, headers)
    with tenant_connection(ctx) as conn:
        result = receipts.begin(conn, ctx.org_id, "extraction.correct", key, request)
    assert result.status == 201 and result.body == original and result.headers == headers
    assert "receipt_version" not in result.body
    for field in ("actor", "resource", "version"):
        with pytest.raises(HTTPException) as error, tenant_connection(ctx) as conn:
            receipts.begin(
                conn, ctx.org_id, "extraction.correct", key, {**request, field: "changed"}
            )
        assert error.value.status_code == 409


def test_rolled_back_receipt_is_not_replayed(extraction_tenant):
    receipts = _module()
    ctx = _context(extraction_tenant)
    key = str(uuid.uuid4())
    with pytest.raises(ValueError), tenant_connection(ctx) as conn:
        receipts.begin(conn, ctx.org_id, "extraction.create", key, {})
        receipts.save(conn, ctx.org_id, "extraction.create", key, {}, 202, {"version": 1}, {})
        raise ValueError("rollback entire command")
    with tenant_connection(ctx) as conn:
        assert receipts.begin(conn, ctx.org_id, "extraction.create", key, {}) is None


def test_concurrent_same_key_blocks_until_exact_first_commit(extraction_tenant, extraction_url):
    receipts = _module()
    ctx = _context(extraction_tenant)
    key = str(uuid.uuid4())
    pids = queue.Queue()

    def second():
        with tenant_connection(ctx) as conn:
            pids.put(conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            return receipts.begin(conn, ctx.org_id, "extraction.review:accept", key, {"ids": ["a"]})

    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_connection(ctx) as conn:
            first_pid = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            assert (
                receipts.begin(conn, ctx.org_id, "extraction.review:accept", key, {"ids": ["a"]})
                is None
            )
            future = pool.submit(second)
            second_pid = pids.get(timeout=3)
            with psycopg.connect(extraction_url, autocommit=True) as observer:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    blockers = observer.execute(
                        "SELECT pg_blocking_pids(%s)", (second_pid,)
                    ).fetchone()[0]
                    if first_pid in blockers:
                        break
                    time.sleep(0.01)
                assert (
                    first_pid in blockers
                ), "second receipt reader did not block on first transaction"
            receipts.save(
                conn,
                ctx.org_id,
                "extraction.review:accept",
                key,
                {"ids": ["a"]},
                200,
                {"version": 1},
                {"ETag": '"v1"'},
            )
        result = future.result(timeout=3)
    assert result.body == {"version": 1} and result.headers == {"ETag": '"v1"'}
