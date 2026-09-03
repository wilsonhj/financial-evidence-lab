"""PostgreSQL SKIP LOCKED job queue (contract job-envelope/v1).

Claim in a short transaction, process outside it, heartbeat while running,
and reap stale claims. Terminal states are exactly succeeded/failed/cancelled.

Retries are bounded in three ways (issue #189, migration 0007): a failed
attempt is rescheduled with exponential backoff rather than requeued for an
immediate re-claim; a stale claim is only requeued while attempts remain and
is otherwise dead-lettered; and a job can be asked to stop cooperatively
through ``cancel_requested_at`` / :func:`is_cancel_requested`.
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fel_workers.redact import redact_job_error_text

HEARTBEAT_STALE_SECONDS = 60

# Retry backoff (issue #189). A failed attempt used to be requeued for an
# immediate re-claim, so a job failing on a transient dependency burned its
# whole attempts budget in milliseconds. Delay is exponential in the attempt
# number, capped, and jittered so a fleet that failed together does not
# retry together.
RETRY_BACKOFF_BASE_SECONDS = 5.0
RETRY_BACKOFF_FACTOR = 2.0
RETRY_BACKOFF_CAP_SECONDS = 900.0  # 15 minutes
RETRY_BACKOFF_JITTER = 0.25
"""Equal jitter: the delay is spread over +/- this fraction of itself."""

# Reaper dead-letter envelope. A fixed operator-facing string: the reaper has
# no handler exception to report, and a constant cannot leak a payload. It
# still goes through the queue's sanitizer so the envelope has exactly one
# construction path.
_REAPED_EXHAUSTED_MESSAGE = redact_job_error_text(
    "stale claim reaped with no attempts remaining; the worker holding this job"
    " stopped heartbeating and the job has exhausted max_attempts"
)


def backoff_seconds(attempts: int, *, rng: random.Random | None = None) -> float:
    """Delay before the ``attempts``-th failed attempt may be re-claimed.

    Pure and deterministic for a given ``rng``; tests inject a seeded
    :class:`random.Random` (or one whose ``random()`` is fixed) instead of
    asserting on a range.
    """
    exponent = max(attempts - 1, 0)
    delay = min(
        RETRY_BACKOFF_BASE_SECONDS * (RETRY_BACKOFF_FACTOR**exponent),
        RETRY_BACKOFF_CAP_SECONDS,
    )
    draw = (rng or random).random()
    jittered = delay * (1.0 + RETRY_BACKOFF_JITTER * (2.0 * draw - 1.0))
    return max(0.0, min(jittered, RETRY_BACKOFF_CAP_SECONDS))


class ReapOutcome(int):
    """How many stale claims a reap touched, split by what happened to them.

    Subclasses ``int`` (valued at the total) so existing callers that treat
    ``reap_stale``'s result as a count -- ``if reaped:``, ``%d`` logging,
    ``total += reap_stale(...)`` -- keep working unchanged, while callers that
    care can read the split.
    """

    requeued: int
    dead_lettered: int

    def __new__(cls, requeued: int, dead_lettered: int) -> ReapOutcome:
        outcome = super().__new__(cls, requeued + dead_lettered)
        outcome.requeued = requeued
        outcome.dead_lettered = dead_lettered
        return outcome

    def __repr__(self) -> str:
        return f"ReapOutcome(requeued={self.requeued}, dead_lettered={self.dead_lettered})"


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
    org_id: str | None = None
    """Tenant binding from the jobs row when present; handlers should reject
    payloads whose org_id disagrees with this value."""


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
    """Short claiming transaction; returns None when the queue is drained.

    A job scheduled into the future by :func:`fail`'s retry backoff is not
    drained, only not yet due: ``available_at <= now()`` skips it and the next
    ready job (if any) is claimed instead.
    """
    with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        row = cur.execute(
            """
            SELECT id, kind, queue, payload, attempts, max_attempts, org_id FROM jobs
            WHERE queue = %s AND status = 'queued' AND available_at <= now()
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
            " heartbeat_at = now(), started_at = now(), lease = %s WHERE id = %s",
            (lease, row["id"]),
        )
        org_raw = row.get("org_id")
        return ClaimedJob(
            id=str(row["id"]),
            kind=row["kind"],
            queue=row["queue"],
            payload=dict(row["payload"]),
            attempts=row["attempts"] + 1,
            max_attempts=row["max_attempts"],
            lease=lease,
            org_id=str(org_raw) if org_raw is not None else None,
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


def fail(
    conn: psycopg.Connection,
    job: ClaimedJob,
    message: str,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> bool:
    """Fenced: requeue until max_attempts is exhausted, then park as failed.
    False means the lease was lost and nothing was written.

    A requeue is scheduled, not immediate: ``available_at`` moves
    :func:`backoff_seconds` into the future so the next attempt waits out the
    transient condition. ``now`` and ``rng`` are injection points for tests --
    with both supplied the scheduled instant is exactly reproducible; with
    neither, the database clock and the module RNG are used.
    """
    terminal = job.attempts >= job.max_attempts
    delay_seconds = 0.0 if terminal else backoff_seconds(job.attempts, rng=rng)
    cur = conn.execute(
        "UPDATE jobs SET status = %s, finished_at = CASE WHEN %s THEN now() END,"
        " available_at = COALESCE(%s::timestamptz, now()) + make_interval(secs => %s),"
        " error = %s, lease = NULL WHERE id = %s AND lease = %s AND status = 'running'",
        (
            "failed" if terminal else "queued",
            terminal,
            now,
            delay_seconds,
            json.dumps(
                {
                    "error": {
                        "code": "JOB_FAILED",
                        # Queue-specific sanitization keeps quoted operational
                        # identifiers readable while masking credential forms.
                        # Arbitrary payload/document values are removed at the
                        # source; the queue remains a defense-in-depth boundary.
                        "message": redact_job_error_text(message),
                        "request_id": job.id,
                    }
                }
            ),
            job.id,
            job.lease,
        ),
    )
    return bool(cur.rowcount)


class PermanentFailure(RuntimeError):
    """A handler raised this to say the job can never succeed.

    The consumer must dead-letter the job immediately (``dead_letter``) instead
    of requeueing it for another attempt. The canonical case is an extraction
    job whose run row is already terminal: migration 0004 forbids reopening it,
    so every retry would fail identically (issue #146, Option 1).
    """


def dead_letter(conn: psycopg.Connection, job: ClaimedJob, message: str) -> bool:
    """Fenced terminal write that parks the job as ``failed`` regardless of the
    attempts remaining. False means the lease was lost and nothing was written."""
    cur = conn.execute(
        "UPDATE jobs SET status = 'failed', finished_at = now(), error = %s, lease = NULL"
        " WHERE id = %s AND lease = %s AND status = 'running'",
        (
            json.dumps(
                {
                    "error": {
                        "code": "JOB_PERMANENT_FAILURE",
                        "message": redact_job_error_text(message),
                        "request_id": job.id,
                    }
                }
            ),
            job.id,
            job.lease,
        ),
    )
    return bool(cur.rowcount)


def cancel(conn: psycopg.Connection, job: ClaimedJob, message: str) -> bool:
    """Fenced terminal write for a job whose handler wound itself down.

    Cancellation is cooperative (see :func:`is_cancel_requested`): the handler
    polls at stage boundaries and brings its own run to a consistent
    ``cancelled`` state, then the consumer records the same verdict on the job.
    Without this primitive a cancelled handler outcome fell through to
    :func:`complete`, so the job read ``succeeded`` while its run read
    ``cancelled`` (issue #204) -- the two halves of one outcome disagreeing.

    Mirrors :func:`complete` and :func:`dead_letter`: terminal, lease-fenced,
    attempts-independent, with a sanitized error envelope. False means the
    lease was lost and nothing was written.
    """
    cur = conn.execute(
        "UPDATE jobs SET status = 'cancelled', finished_at = now(), error = %s, lease = NULL"
        " WHERE id = %s AND lease = %s AND status = 'running'",
        (
            json.dumps(
                {
                    "error": {
                        "code": "JOB_CANCELLED",
                        "message": redact_job_error_text(message),
                        "request_id": job.id,
                    }
                }
            ),
            job.id,
            job.lease,
        ),
    )
    return bool(cur.rowcount)


def reap_stale(
    conn: psycopg.Connection, *, stale_seconds: float = HEARTBEAT_STALE_SECONDS
) -> ReapOutcome:
    """Recover running jobs whose worker stopped heartbeating.

    A stale claim with attempts left is requeued (available immediately -- the
    attempt never got to run, so there is nothing transient to wait out). A
    stale claim with none left is dead-lettered as ``failed`` with a
    ``REAPED_EXHAUSTED`` envelope: before #189 the reaper requeued every stale
    row with no attempts check, so a job that reliably killed its worker was
    reaped, re-claimed and killed again forever.

    ``stale_seconds`` defaults to the contract threshold; tests inject a
    shorter one to exercise reaping without real minute-long waits.
    """
    cur = conn.execute(
        """
        UPDATE jobs SET
            status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
            lease = NULL,
            available_at = CASE WHEN attempts < max_attempts THEN now() ELSE available_at END,
            finished_at = CASE WHEN attempts < max_attempts THEN finished_at ELSE now() END,
            error = CASE
                WHEN attempts < max_attempts THEN error
                ELSE jsonb_build_object(
                    'error',
                    jsonb_build_object(
                        'code', 'REAPED_EXHAUSTED',
                        'message', %s::text,
                        'request_id', id::text
                    )
                )
            END
        WHERE status = 'running'
          AND heartbeat_at < now() - make_interval(secs => %s)
        RETURNING status
        """,
        (_REAPED_EXHAUSTED_MESSAGE, stale_seconds),
    )
    statuses = [row[0] for row in cur.fetchall()]
    return ReapOutcome(
        requeued=sum(1 for status in statuses if status == "queued"),
        dead_lettered=sum(1 for status in statuses if status == "failed"),
    )


def is_cancel_requested(conn: psycopg.Connection, *, job_id: str) -> bool:
    """True once someone asked for this job to stop.

    Cancellation is cooperative and advisory: ``cancel_requested_at`` is set by
    the API role (migration 0007 grants exactly that one column) and never
    changes ``status`` on its own. Handlers poll this at stage boundaries and
    wind the run down themselves, so a partially written run reaches a
    consistent terminal state instead of being torn out from under a worker.
    An unknown job id reads as not cancelled.
    """
    row = conn.execute(
        "SELECT cancel_requested_at IS NOT NULL FROM jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    return bool(row[0]) if row is not None else False
