"""PostgreSQL SKIP LOCKED job queue (contract job-envelope/v1).

Claim in a short transaction, process outside it, heartbeat while running,
and reap stale claims back to queued. Terminal states are exactly
succeeded/failed/cancelled.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

HEARTBEAT_STALE_SECONDS = 60


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    kind: str
    queue: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    lease: str
    """Per-claim fencing token: every state update requires the lease, so a
    worker whose claim was reaped can no longer write a terminal state."""


def enqueue(
    conn: psycopg.Connection,
    *,
    kind: str,
    payload: dict[str, Any],
    queue: str = "default",
    priority: int = 5,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
    org_id: str | None = None,
) -> str:
    """Insert a job. Idempotency is scoped per (org_id, kind, idempotency_key)
    so tenants can never collide on a shared client key; a repeat within that
    scope returns the original job id."""
    job_id = str(uuid.uuid4())
    if idempotency_key is None:
        row = conn.execute(
            "INSERT INTO jobs (id, kind, queue, priority, payload, org_id, max_attempts)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (job_id, kind, queue, priority, json.dumps(payload), org_id, max_attempts),
        ).fetchone()
    else:
        row = conn.execute(
            """
            INSERT INTO jobs
                (id, kind, queue, priority, payload, org_id, idempotency_key, max_attempts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (org_id, kind, idempotency_key) WHERE idempotency_key IS NOT NULL
            DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
            RETURNING id
            """,
            (
                job_id,
                kind,
                queue,
                priority,
                json.dumps(payload),
                org_id,
                idempotency_key,
                max_attempts,
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("enqueue returned no row")
    return str(row[0])


def claim_one(conn: psycopg.Connection, *, queue: str = "default") -> ClaimedJob | None:
    """Short claiming transaction; returns None when the queue is drained."""
    with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        row = cur.execute(
            """
            SELECT id, kind, queue, payload, attempts, max_attempts FROM jobs
            WHERE queue = %s AND status = 'queued'
            ORDER BY priority, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """,
            (queue,),
        ).fetchone()
        if row is None:
            return None
        lease = str(uuid.uuid4())
        cur.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1,"
            " heartbeat_at = now(), lease = %s WHERE id = %s",
            (lease, row["id"]),
        )
        return ClaimedJob(
            id=str(row["id"]),
            kind=row["kind"],
            queue=row["queue"],
            payload=dict(row["payload"]),
            attempts=row["attempts"] + 1,
            max_attempts=row["max_attempts"],
            lease=lease,
        )


def heartbeat(conn: psycopg.Connection, job: ClaimedJob) -> bool:
    """False means the lease was lost (reaped and possibly re-claimed)."""
    cur = conn.execute(
        "UPDATE jobs SET heartbeat_at = now()"
        " WHERE id = %s AND lease = %s AND status = 'running'",
        (job.id, job.lease),
    )
    return bool(cur.rowcount)


def complete(conn: psycopg.Connection, job: ClaimedJob) -> bool:
    """Fenced terminal write; False means the lease was lost and the result
    must be discarded (another worker owns the job now)."""
    cur = conn.execute(
        "UPDATE jobs SET status = 'succeeded', finished_at = now(), lease = NULL"
        " WHERE id = %s AND lease = %s AND status = 'running'",
        (job.id, job.lease),
    )
    return bool(cur.rowcount)


def fail(conn: psycopg.Connection, job: ClaimedJob, message: str) -> bool:
    """Fenced: requeue until max_attempts is exhausted, then park as failed.
    False means the lease was lost and nothing was written."""
    terminal = job.attempts >= job.max_attempts
    cur = conn.execute(
        "UPDATE jobs SET status = %s, finished_at = CASE WHEN %s THEN now() END,"
        " error = %s, lease = NULL WHERE id = %s AND lease = %s AND status = 'running'",
        (
            "failed" if terminal else "queued",
            terminal,
            json.dumps({"error": {"code": "JOB_FAILED", "message": message, "request_id": job.id}}),
            job.id,
            job.lease,
        ),
    )
    return bool(cur.rowcount)


def reap_stale(conn: psycopg.Connection) -> int:
    """Requeue running jobs whose worker stopped heartbeating."""
    cur = conn.execute(
        """
        UPDATE jobs SET status = 'queued', lease = NULL
        WHERE status = 'running'
          AND heartbeat_at < now() - make_interval(secs => %s)
        """,
        (HEARTBEAT_STALE_SECONDS,),
    )
    return cur.rowcount or 0
