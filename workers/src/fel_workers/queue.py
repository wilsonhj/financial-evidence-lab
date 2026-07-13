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


def enqueue(
    conn: psycopg.Connection,
    *,
    kind: str,
    payload: dict[str, Any],
    queue: str = "default",
    priority: int = 5,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
) -> str:
    """Insert a job; an existing idempotency key returns the original job id."""
    job_id = str(uuid.uuid4())
    row = conn.execute(
        """
        INSERT INTO jobs (id, kind, queue, priority, payload, idempotency_key, max_attempts)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
        RETURNING id
        """,
        (job_id, kind, queue, priority, json.dumps(payload), idempotency_key, max_attempts),
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
        cur.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1,"
            " heartbeat_at = now() WHERE id = %s",
            (row["id"],),
        )
        return ClaimedJob(
            id=str(row["id"]),
            kind=row["kind"],
            queue=row["queue"],
            payload=dict(row["payload"]),
            attempts=row["attempts"] + 1,
            max_attempts=row["max_attempts"],
        )


def heartbeat(conn: psycopg.Connection, job_id: str) -> None:
    conn.execute("UPDATE jobs SET heartbeat_at = now() WHERE id = %s", (job_id,))


def complete(conn: psycopg.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'succeeded', finished_at = now() WHERE id = %s",
        (job_id,),
    )


def fail(conn: psycopg.Connection, job: ClaimedJob, message: str) -> None:
    """Requeue until max_attempts is exhausted, then park as failed."""
    terminal = job.attempts >= job.max_attempts
    conn.execute(
        "UPDATE jobs SET status = %s, finished_at = CASE WHEN %s THEN now() END,"
        " error = %s WHERE id = %s",
        (
            "failed" if terminal else "queued",
            terminal,
            json.dumps({"error": {"code": "JOB_FAILED", "message": message, "request_id": job.id}}),
            job.id,
        ),
    )


def reap_stale(conn: psycopg.Connection) -> int:
    """Requeue running jobs whose worker stopped heartbeating."""
    cur = conn.execute(
        """
        UPDATE jobs SET status = 'queued'
        WHERE status = 'running'
          AND heartbeat_at < now() - make_interval(secs => %s)
        """,
        (HEARTBEAT_STALE_SECONDS,),
    )
    return cur.rowcount or 0
