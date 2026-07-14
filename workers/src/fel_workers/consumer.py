"""Job consumer: claims queued jobs and dispatches them to handlers (T0105).

Closes the discovery -> fetch loop: discovery enqueues
``sec_filing_fetch`` jobs, and this dispatcher claims them
(``queue.claim_one``), fetches the filing through the injected ``SecClient``
protocol, runs the idempotent ingestion pipeline, and completes/fails the
job through the lease-fenced queue primitives — a worker whose claim was
reaped can never write a terminal state. While a handler runs, a background
:class:`LeaseHeartbeat` thread keeps the lease fresh (so long jobs are not
reaped), and the loop itself periodically calls ``queue.reap_stale`` so jobs
abandoned by crashed workers are requeued. ``sec_discovery`` jobs are routed
to the discovery handler so the whole chain runs off one queue.
``sec_company_facts`` jobs (issue #83) dispatch through a runtime
``isinstance`` narrow onto the workers-local ``CompanyFactsSecClient``
capability; a bound client without it fails the job like an unknown kind.

All collaborators (connection, storage, SEC client, sleep) are injected;
tests drive the loop with ``max_iterations`` against mocks and a real
Postgres. ``python -m fel_workers run`` wires this loop as the process
entrypoint.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg

from fel_providers.interfaces import SecClient, StorageProvider
from fel_workers import queue
from fel_workers.ingestion.company_facts import (
    JOB_KIND_SEC_COMPANY_FACTS,
    CompanyFactsSecClient,
    entity_id_for_cik,
    handle_sec_company_facts,
)
from fel_workers.ingestion.discovery import (
    JOB_KIND_SEC_DISCOVERY,
    JOB_KIND_SEC_FILING_FETCH,
    run_discovery_job,
)
from fel_workers.ingestion.pipeline import IngestionOutcome, ingest_filing

__all__ = [
    "DEFAULT_QUEUE",
    "LeaseHeartbeat",
    "entity_id_for_cik",
    "handle_sec_filing_fetch",
    "run_worker",
]

log = logging.getLogger("fel_workers.consumer")

DEFAULT_QUEUE = "ingestion"

# Beat well under queue.HEARTBEAT_STALE_SECONDS (60s) so a healthy worker's
# claim is always fresh when a reaper looks at it.
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15.0


class LeaseHeartbeat:
    """Daemon thread that keeps a claimed job's lease fresh while the handler
    runs, on its own DB connection (the worker connection is busy with the
    handler's statements).

    Beats every ``interval_seconds`` — well under the reaper threshold — and
    latches ``lease_lost`` the moment :func:`queue.heartbeat` returns False:
    the claim was reaped and possibly re-claimed, so the running handler's
    result must be discarded (the new owner wins). A heartbeat *connection*
    failure is not proof of loss; it is logged and beating stops, and the
    fenced terminal write still decides ownership.
    """

    def __init__(
        self,
        connection_factory: Callable[[], psycopg.Connection[Any]],
        job: queue.ClaimedJob,
        *,
        interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._connection_factory = connection_factory
        self._job = job
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lease_lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"lease-heartbeat-{job.id}", daemon=True
        )

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Stop beating and wait for the thread to exit."""
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        try:
            with self._connection_factory() as conn:
                while not self._stop.wait(self._interval_seconds):
                    if not queue.heartbeat(conn, self._job):
                        self._lease_lost.set()
                        log.warning("lease lost mid-job %s (heartbeat fenced out)", self._job.id)
                        return
        except Exception:  # noqa: BLE001 — heartbeat must never kill the worker
            log.exception("heartbeat connection failed for job %s", self._job.id)


def _connection_factory_like(
    conn: psycopg.Connection[Any],
) -> Callable[[], psycopg.Connection[Any]]:
    """Default heartbeat connection factory: clone the worker connection's
    DSN (``conn.info.dsn`` omits the password, so it is re-supplied)."""
    dsn = conn.info.dsn
    password = conn.info.password or None

    def factory() -> psycopg.Connection[Any]:
        return psycopg.connect(dsn, password=password, autocommit=True)

    return factory


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
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    heartbeat_connection_factory: Callable[[], psycopg.Connection[Any]] | None = None,
    reap_interval_iterations: int = 1,
    stale_after_seconds: float = queue.HEARTBEAT_STALE_SECONDS,
) -> int:
    """Claim-and-dispatch loop; returns the number of jobs completed.

    With ``max_iterations`` set (tests), the loop performs at most that
    many claim attempts and stops early once the queue drains; without it,
    the loop runs until ``should_continue`` (e.g. a signal flag) turns
    false, sleeping ``idle_sleep_seconds`` when idle.

    Lease contract (queue.py): while a handler runs, a :class:`LeaseHeartbeat`
    daemon thread beats the claim every ``heartbeat_interval_seconds`` on its
    own connection so long-running jobs are never mistaken for dead ones, and
    every ``reap_interval_iterations`` claim attempts the loop calls
    :func:`queue.reap_stale` (threshold ``stale_after_seconds``) so jobs whose
    worker crashed are requeued instead of staying 'running' forever. If the
    heartbeat reports the lease lost, the job is treated as lost: the handler
    result is discarded and no terminal state is written — the new owner wins.
    """
    completed = 0
    iterations = 0
    connection_factory = heartbeat_connection_factory or _connection_factory_like(conn)
    while should_continue() and (max_iterations is None or iterations < max_iterations):
        iterations += 1
        if reap_interval_iterations > 0 and (iterations - 1) % reap_interval_iterations == 0:
            reaped = queue.reap_stale(conn, stale_seconds=stale_after_seconds)
            if reaped:
                log.warning("reaped %d stale job(s) back to queued", reaped)
        job = queue.claim_one(conn, queue=queue_name)
        if job is None:
            if max_iterations is not None:
                break
            sleep(idle_sleep_seconds)
            continue
        if job.kind not in (
            JOB_KIND_SEC_DISCOVERY,
            JOB_KIND_SEC_FILING_FETCH,
            JOB_KIND_SEC_COMPANY_FACTS,
        ):
            queue.fail(conn, job, f"unknown job kind {job.kind!r}")
            continue
        # Capability narrowing (issue #83): sec_company_facts needs the
        # workers-local CompanyFactsSecClient capability on top of the frozen
        # SecClient protocol; a bound client without it fails the job
        # exactly like an unknown kind (mypy-strict-safe isinstance narrow).
        company_facts_client: CompanyFactsSecClient | None = None
        if job.kind == JOB_KIND_SEC_COMPANY_FACTS:
            if isinstance(sec, CompanyFactsSecClient):
                company_facts_client = sec
            else:
                queue.fail(
                    conn,
                    job,
                    f"bound SecClient {type(sec).__name__} lacks the "
                    f"company_facts capability required by job kind {job.kind!r}",
                )
                continue
        heartbeat = LeaseHeartbeat(
            connection_factory, job, interval_seconds=heartbeat_interval_seconds
        )
        heartbeat.start()
        try:
            if job.kind == JOB_KIND_SEC_DISCOVERY:
                run_discovery_job(conn, sec, job.payload, job_queue=queue_name)
            elif job.kind == JOB_KIND_SEC_COMPANY_FACTS:
                if company_facts_client is None:  # pragma: no cover — narrowed above
                    raise RuntimeError("company_facts capability vanished mid-dispatch")
                outcome = handle_sec_company_facts(conn, storage, company_facts_client, job.payload)
                log.info(
                    "ingested companyfacts cik=%s -> %s (%s)",
                    job.payload.get("cik"),
                    outcome.status,
                    outcome.reason_code or "ok",
                )
            else:
                outcome = handle_sec_filing_fetch(conn, storage, sec, job.payload)
                log.info(
                    "ingested %s -> %s (%s)",
                    job.payload.get("accession"),
                    outcome.status,
                    outcome.reason_code or "ok",
                )
        except Exception as exc:  # noqa: BLE001 — job isolation boundary
            heartbeat.stop()
            if heartbeat.lease_lost:
                log.warning("lease lost during job %s; failure not recorded", job.id)
                continue
            log.exception("job %s failed", job.id)
            queue.fail(conn, job, str(exc))
            continue
        heartbeat.stop()
        # Lost lease means another worker owns the job now; the fenced
        # complete below would refuse the write anyway, but we skip it
        # explicitly so the outcome is deliberate, not incidental.
        if heartbeat.lease_lost:
            log.warning("lease lost during job %s; result discarded", job.id)
            continue
        # Fenced completion: if the lease was reaped between the last
        # heartbeat and now, the terminal write is refused and discarded.
        if queue.complete(conn, job):
            completed += 1
        else:
            log.warning("lease lost during job %s; result discarded", job.id)
    return completed
