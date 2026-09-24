"""Exact extraction receipts in the existing tenant transaction and table."""

import json
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.errors import api_error
from fel_workers.extraction.hashing import canonical_json, hash_json


@dataclass(frozen=True)
class Receipt:
    status: int
    body: dict[str, Any]
    headers: dict[str, str]


def begin(
    conn: psycopg.Connection[dict[str, Any]],
    org_id: str,
    endpoint: str,
    key: str,
    request: dict[str, Any],
) -> Receipt | None:
    """Acquire before any run/group/proposal/head lock; replay before preconditions."""
    digest = hash_json([org_id, endpoint, key]).removeprefix("sha256:")
    lock = int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    row = conn.execute(
        "SELECT response_status, response_body FROM idempotency_keys "
        "WHERE org_id=%s AND endpoint=%s AND key=%s",
        (org_id, endpoint, key),
    ).fetchone()
    if row is None:
        return None
    envelope = row["response_body"]
    if envelope.get("receipt_version") != "extraction-receipt/v1" or envelope.get(
        "request_hash"
    ) != hash_json(request):
        raise api_error(
            409, "IDEMPOTENCY_KEY_REUSED", "Idempotency key belongs to another request."
        )
    return Receipt(
        row["response_status"],
        json.loads(canonical_json(envelope["body"])),
        envelope["response_headers"],
    )


def save(
    conn: psycopg.Connection[dict[str, Any]],
    org_id: str,
    endpoint: str,
    key: str,
    request: dict[str, Any],
    status: int,
    body: dict[str, Any],
    headers: dict[str, str],
) -> Receipt:
    """Caller already holds begin's lock; no commit or independently acquired connection."""
    envelope = {
        "receipt_version": "extraction-receipt/v1",
        "request_hash": hash_json(request),
        "response_headers": headers,
        "body": body,
    }
    conn.execute(
        "INSERT INTO idempotency_keys(key,org_id,endpoint,response_status,response_body) "
        "VALUES (%s,%s,%s,%s,%s)",
        (key, org_id, endpoint, status, Jsonb(envelope)),
    )
    return Receipt(status, json.loads(canonical_json(body)), headers)
