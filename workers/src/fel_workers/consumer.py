"""Job consumer: claims queued jobs and dispatches them to handlers (T0105).

Closes the discovery -> fetch loop: discovery enqueues
``sec_filing_fetch`` jobs, and this dispatcher claims them
(``queue.claim_one``), fetches the filing through the injected ``SecClient``
protocol, runs the idempotent ingestion pipeline, and completes/fails the
job through the lease-fenced queue primitives — a worker whose claim was
reaped can never write a terminal state. ``sec_discovery`` jobs are routed
to the discovery handler so the whole chain runs off one queue.

All collaborators (connection, storage, SEC client, sleep) are injected;
tests drive the loop with ``max_iterations`` against mocks and a real
Postgres. ``python -m fel_workers run`` wires this loop as the process
entrypoint.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg

from fel_providers.interfaces import SecClient, StorageProvider
from fel_workers import queue
from fel_workers.ingestion.discovery import (
    JOB_KIND_SEC_DISCOVERY,
    JOB_KIND_SEC_FILING_FETCH,
    run_discovery_job,
)
from fel_workers.ingestion.parser import ID_NAMESPACE
from fel_workers.ingestion.pipeline import IngestionOutcome, ingest_filing
from fel_workers.ingestion.sec_client import normalize_cik

log = logging.getLogger("fel_workers.consumer")

DEFAULT_QUEUE = "ingestion"


def entity_id_for_cik(cik: str) -> str:
    """Deterministic entity id for an SEC issuer (uuid5 over the CIK)."""
    return str(uuid.uuid5(ID_NAMESPACE, f"entity|{normalize_cik(cik)}"))


def handle_sec_filing_fetch(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    sec: SecClient,
    payload: dict[str, Any],
) -> IngestionOutcome:
    """Fetch one discovered filing and run the ingestion pipeline on it."""
    url = str(payload.get("url") or "")
    accession = str(payload.get("accession") or "")
    cik = str(payload.get("cik") or "")
    if not url or not accession or not cik:
        raise ValueError(f"sec_filing_fetch payload is missing url/accession/cik: {payload!r}")
    form = str(payload["form"]) if payload.get("form") else None
    filed_on_text = str(payload.get("filed_on") or "")
    filed_at = datetime.fromisoformat(filed_on_text)
    if filed_at.tzinfo is None:
        # Discovery records the EDGAR filing DATE; midnight UTC is the
        # earliest conservative instant for point-in-time filtering.
        filed_at = filed_at.replace(tzinfo=UTC)
    raw = sec.fetch_document(url)
    return ingest_filing(
        conn,
        storage,
        entity_id=entity_id_for_cik(cik),
        accession=accession,
        source_url=url,
        raw=raw,
        published_at=filed_at,
        form=form,
        filed_at=filed_at,
    )


def run_worker(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    sec: SecClient,
    *,
    queue_name: str = DEFAULT_QUEUE,
    max_iterations: int | None = None,
    idle_sleep_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    should_continue: Callable[[], bool] = lambda: True,
) -> int:
    """Claim-and-dispatch loop; returns the number of jobs completed.

    With ``max_iterations`` set (tests), the loop performs at most that
    many claim attempts and stops early once the queue drains; without it,
    the loop runs until ``should_continue`` (e.g. a signal flag) turns
    false, sleeping ``idle_sleep_seconds`` when idle.
    """
    completed = 0
    iterations = 0
    while should_continue() and (max_iterations is None or iterations < max_iterations):
        iterations += 1
        job = queue.claim_one(conn, queue=queue_name)
        if job is None:
            if max_iterations is not None:
                break
            sleep(idle_sleep_seconds)
            continue
        if not queue.heartbeat(conn, job):
            log.warning("lease lost before start; skipping job %s", job.id)
            continue
        try:
            if job.kind == JOB_KIND_SEC_DISCOVERY:
                run_discovery_job(conn, sec, job.payload, job_queue=queue_name)
            elif job.kind == JOB_KIND_SEC_FILING_FETCH:
                outcome = handle_sec_filing_fetch(conn, storage, sec, job.payload)
                log.info(
                    "ingested %s -> %s (%s)",
                    job.payload.get("accession"),
                    outcome.status,
                    outcome.reason_code or "ok",
                )
            else:
                queue.fail(conn, job, f"unknown job kind {job.kind!r}")
                continue
        except Exception as exc:  # noqa: BLE001 — job isolation boundary
            log.exception("job %s failed", job.id)
            queue.fail(conn, job, str(exc))
            continue
        # Fenced heartbeat + completion: if the lease was reaped while we
        # worked, the terminal write is refused and the result discarded.
        if queue.complete(conn, job):
            completed += 1
        else:
            log.warning("lease lost during job %s; result discarded", job.id)
    return completed
