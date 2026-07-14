"""T0112: benchmark-cohort ingestion harness + corpus-quality metrics.

Reads the canonical cohort ``evals/datasets/issuer-cohort.json`` (read
only), drives discovery -> fetch -> ingest through the REAL job consumer
(``fel_workers.consumer.run_worker``) against a real Postgres, then
computes corpus-quality metrics and records them to a versioned JSON
report under ``evals/reports/corpus-qa/``. Schema:
``evals/reports/corpus-qa/SCHEMA.md`` (contract corpus-qa-report/v1).

Synthetic mode (default; NO network) keys every database row by a
NAMESPACED SYNTHETIC identity (:func:`synthetic_cik` /
:func:`synthetic_entity_id`, derived from a synthetic UUID namespace over
the cohort ticker) — never by the real cohort CIKs/entity ids — so
synthetic rows can never collide with a live run's discovery idempotency
keys or corpus rows in the same database:

    TEST_DATABASE_URL="postgresql://..." \\
    PYTHONPATH=evals:workers/src:packages/providers:apps/api \\
    .venv/bin/python -m harness.corpus_qa \\
        --mode synthetic --reset-corpus --i-know-this-destroys-data \\
        --reports-dir evals/reports/corpus-qa --label <date>-synthetic-cohort

Live mode (SEC egress + fair-access compliance REQUIRED; never run from
CI or an egress-blocked session) requires ``FEL_SEC_USER_AGENT`` — a
non-empty SEC fair-access identity containing an ``@`` contact marker,
mirroring the worker deployment gate — and fails with exit 2 BEFORE any
network access when it is absent or malformed:

    FEL_DATABASE_URL="postgresql://..." \\
    FEL_SEC_USER_AGENT="org-or-app name (contact@example.com)" \\
    PYTHONPATH=evals:workers/src:packages/providers:apps/api \\
    .venv/bin/python -m harness.corpus_qa \\
        --mode live --storage-dir /var/fel/storage \\
        --forms 10-K,10-Q,10-Q/A \\
        --reports-dir evals/reports/corpus-qa --label <date>-live-cohort

``--reset-corpus`` is DESTRUCTIVE and fails closed (exit 2, before any
connection): it never falls back to ``FEL_DATABASE_URL`` (only
``TEST_DATABASE_URL`` or an explicit ``--database-url``), additionally
requires ``--i-know-this-destroys-data``, and refuses any target whose
database name does not end in ``_test`` unless
``FEL_HARNESS_ALLOW_RESET=1`` explicitly marks the target disposable.

Metrics are computed strictly from THIS run's outputs: the harness lists
the run's expected filings up front (same submissions index the pipeline
uses), records every expected job's terminal outcome from the queryable
``jobs`` table, and aggregates corpus metrics over exactly the run's
(entity, accession) set — never over global/historical table contents.
A run that leaves expected jobs failed/pending/missing, or exhausts its
iteration budget with a backlog, is a RUN FAILURE (nonzero exit; report
marked non-acceptance).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import conninfo
from psycopg.rows import dict_row

from fel_providers.interfaces import SecClient, StorageProvider
from fel_providers.mocks import MockStorageProvider
from fel_workers import queue
from fel_workers.consumer import entity_id_for_cik, run_worker
from fel_workers.ingestion.discovery import (
    JOB_KIND_SEC_DISCOVERY,
    JOB_KIND_SEC_FILING_FETCH,
    FilingRef,
    discover_filings,
)
from fel_workers.ingestion.parser import PARSER_VERSION
from fel_workers.ingestion.xbrl import NORMALIZER_VERSION
from fel_workers.storage import LocalDirStorageProvider
from harness.synthetic_sec import SyntheticCohortSecClient

REPORT_SCHEMA = "corpus-qa-report/v1"
REPORT_SCHEMA_VERSION = 1
DEFAULT_COHORT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "datasets" / "issuer-cohort.json"
)
DEFAULT_QUEUE = "ingestion"
DEFAULT_LIVE_FORMS = ("10-K", "10-Q", "10-Q/A")
DEFAULT_MAX_ITERATIONS = 10_000

# Synthetic identity namespace: synthetic runs NEVER key database rows by
# the real cohort CIKs/entity ids. Each cohort slot gets a deterministic
# 12-digit synthetic CIK derived from this namespace + the slot ticker;
# real normalized CIKs are exactly 10 digits, so the two identity spaces
# (and every id derived from them — entity ids, accessions, fetch-job
# idempotency keys) are disjoint by construction.
SYNTHETIC_CIK_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://financial-evidence-lab.dev/evals/corpus-qa/synthetic-issuer"
)
SYNTHETIC_CIK_DIGITS = 12
SYNTHETIC_IDENTITY_NAMESPACE = "fel-corpus-qa-synthetic/v1"
LIVE_IDENTITY_NAMESPACE = "sec-cik"

SYNTHETIC_NOTE = (
    "SYNTHETIC RUN: the pipeline, queue, quarantine, and metrics paths are "
    "real, but every ingested byte was generated from committed synthetic "
    "templates (evals/datasets/synthetic-corpus/). Cohort tickers label "
    "the benchmark slots in this report ONLY — every database row is keyed "
    "by a namespaced synthetic identity, and NO metric in this report "
    "describes any real company's filings."
)
LIVE_NOTE = (
    "LIVE RUN: documents were fetched from SEC EDGAR under the fair-access "
    "policy via the frozen LiveSecClient."
)
ACCEPTANCE_DEFERRED_LIVE_REASON = (
    "synthetic run: T0112 acceptance requires the deferred LIVE cohort run "
    "(no SEC egress in this session); synthetic reports are never "
    "acceptance-grade"
)

RATE_UNAVAILABLE = "unavailable"
_PENDING_STATUSES = ("queued", "claimed", "running")

# FK-safe deletion order for --reset-corpus (disposable databases only).
_RESET_STATEMENTS = (
    "DELETE FROM corpus_version_documents",
    "DELETE FROM corpus_versions",
    "DELETE FROM financial_facts",
    "DELETE FROM tables_meta",
    "DELETE FROM source_spans",
    "DELETE FROM sections",
    "DELETE FROM document_versions",
    "DELETE FROM ingestion_runs",
    "DELETE FROM ingestion_quarantine",
    "DELETE FROM documents",
    "DELETE FROM jobs",
)

# Every metrics query is scoped to THIS run's (entity, accession) set —
# prior runs' rows in the same database are never aggregated.
_ISSUER_DOCUMENTS_SQL = """
    SELECT count(*) AS n FROM documents
    WHERE entity_id = %s AND accession = ANY(%s::text[])
"""
_ISSUER_PARSED_SQL = """
    SELECT count(*) AS n FROM documents d
    WHERE d.entity_id = %s AND d.accession = ANY(%s::text[]) AND EXISTS (
        SELECT 1 FROM document_versions dv
        WHERE dv.document_id = d.id AND dv.status = 'parsed'
    )
"""
_ISSUER_VERSIONS_SQL = """
    SELECT count(*) AS n FROM document_versions dv
    JOIN documents d ON d.id = dv.document_id
    WHERE d.entity_id = %s AND d.accession = ANY(%s::text[]) AND dv.status = 'parsed'
"""
_ISSUER_QUARANTINED_SQL = """
    SELECT count(DISTINCT accession) AS n FROM ingestion_quarantine
    WHERE accession = ANY(%s::text[])
"""
_ISSUER_FACTS_SQL = """
    SELECT count(*) AS total,
           count(*) FILTER (WHERE f.duplicate_of IS NULL) AS canonical,
           count(*) FILTER (WHERE f.duplicate_of IS NOT NULL) AS duplicate,
           count(*) FILTER (WHERE f.restates IS NOT NULL) AS restated
    FROM financial_facts f
    JOIN document_versions dv ON dv.id = f.document_version_id
    JOIN documents d ON d.id = dv.document_id
    WHERE f.entity_id = %s AND d.accession = ANY(%s::text[])
"""
_ISSUER_QUARANTINE_REASONS_SQL = """
    SELECT reason_code, count(*) AS n FROM ingestion_quarantine
    WHERE accession = ANY(%s::text[])
    GROUP BY reason_code ORDER BY reason_code
"""
_ISSUER_TEXT_KEYS_SQL = """
    SELECT dv.id::text AS version_id, dv.canonical_text_key
    FROM document_versions dv
    JOIN documents d ON d.id = dv.document_id
    WHERE d.entity_id = %s AND d.accession = ANY(%s::text[]) AND dv.status = 'parsed'
    ORDER BY dv.id
"""
_VERSION_SPANS_SQL = """
    SELECT start_char, end_char, text_hash FROM source_spans
    WHERE document_version_id = %s ORDER BY start_char, end_char
"""
_JOBS_BY_ID_SQL = """
    SELECT id::text AS id, kind, status, error, payload FROM jobs
    WHERE id = ANY(%s::uuid[])
"""
_FETCH_JOBS_BY_KEY_SQL = """
    SELECT id::text AS id, kind, status, error, payload, idempotency_key FROM jobs
    WHERE kind = %s AND idempotency_key = ANY(%s::text[])
"""
_QUEUE_BACKLOG_SQL = """
    SELECT count(*) AS n FROM jobs
    WHERE queue = %s AND status IN ('queued', 'claimed', 'running')
"""


class HarnessError(Exception):
    """The harness was misconfigured or a run invariant failed (exit 2)."""


# ---------------------------------------------------------------------------
# Identities: cohort slots vs the database keys a run actually uses.
# ---------------------------------------------------------------------------


def synthetic_cik(ticker: str) -> str:
    """Deterministic namespaced synthetic CIK for a cohort slot.

    Derived from :data:`SYNTHETIC_CIK_NAMESPACE` + the slot ticker; always
    ``SYNTHETIC_CIK_DIGITS`` (12) digits, so it can NEVER normalize to any
    real SEC CIK (real normalized CIKs are exactly 10 digits).
    """
    derived = uuid.uuid5(SYNTHETIC_CIK_NAMESPACE, f"issuer|{ticker}")
    return f"{derived.int % 10**SYNTHETIC_CIK_DIGITS:0{SYNTHETIC_CIK_DIGITS}d}"


def synthetic_entity_id(ticker: str) -> str:
    """The entity UUID a synthetic run keys this cohort slot's rows by."""
    return entity_id_for_cik(synthetic_cik(ticker))


@dataclass(frozen=True)
class RunIssuer:
    """One cohort slot resolved to the identity THIS run keys rows by."""

    ticker: str
    cik: str
    """Real cohort CIK — a report label only; never a synthetic DB key."""
    db_cik: str
    """CIK actually fed to discovery/ingestion (synthetic or real)."""
    entity_id: str
    """Entity UUID derived from ``db_cik`` (the database key)."""


def run_issuers(cohort: Cohort, mode: str) -> tuple[RunIssuer, ...]:
    """Resolve every cohort slot to the identity the run will use."""
    issuers = []
    for issuer in cohort.issuers:
        db_cik = synthetic_cik(issuer["ticker"]) if mode == "synthetic" else issuer["cik"]
        issuers.append(
            RunIssuer(
                ticker=issuer["ticker"],
                cik=issuer["cik"],
                db_cik=db_cik,
                entity_id=entity_id_for_cik(db_cik),
            )
        )
    return tuple(issuers)


# ---------------------------------------------------------------------------
# Fail-closed configuration gates (all before any connection or network).
# ---------------------------------------------------------------------------


def require_live_sec_user_agent(environ: Mapping[str, str] = os.environ) -> str:
    """Return the SEC fair-access identity for live mode, failing closed.

    Mirrors the worker deployment gate: ``FEL_SEC_USER_AGENT`` must be
    non-empty and carry an ``@`` contact marker. Raises
    :class:`HarnessError` BEFORE any network access otherwise — live mode
    never falls back to the in-code default identity (a personal contact
    literal kept for library/tests only).
    """
    user_agent = environ.get("FEL_SEC_USER_AGENT", "").strip()
    if not user_agent or "@" not in user_agent:
        raise HarnessError(
            "live mode requires FEL_SEC_USER_AGENT: an SEC fair-access identity"
            " of the shape 'org-or-app name (contact@example.com)' — non-empty"
            " and containing a contact address ('@'). Refusing before any"
            " network access; the in-code default identity is for"
            " library/tests only."
        )
    return user_agent


def ensure_disposable_reset_target(
    database_url: str, environ: Mapping[str, str] = os.environ
) -> None:
    """Refuse a destructive reset unless the target is provably disposable.

    The database name must end with ``_test``, or the operator must set
    ``FEL_HARNESS_ALLOW_RESET=1`` to explicitly mark the target disposable.
    Raises :class:`HarnessError` BEFORE any connection is opened.
    """
    try:
        params = conninfo.conninfo_to_dict(database_url)
    except psycopg.ProgrammingError as exc:
        raise HarnessError(f"--reset-corpus target URL is unparseable: {exc}") from exc
    if environ.get("FEL_HARNESS_ALLOW_RESET") == "1":
        return
    dbname = str(params.get("dbname") or "")
    if not dbname.endswith("_test"):
        raise HarnessError(
            f"--reset-corpus refused: target database {dbname!r} does not end"
            " with '_test', so it is not provably disposable. Deleting the"
            " corpus/queue tables is unrecoverable. Point at a disposable"
            " *_test database, or set FEL_HARNESS_ALLOW_RESET=1 to explicitly"
            " mark this target disposable."
        )


def resolve_database_url(
    *,
    reset: bool,
    explicit_url: str | None,
    confirmed: bool,
    environ: Mapping[str, str] = os.environ,
) -> str:
    """Resolve the target database URL, failing closed for destructive runs.

    The destructive path (``reset=True``) NEVER falls back to
    ``FEL_DATABASE_URL``: only an explicit ``--database-url`` or
    ``TEST_DATABASE_URL`` is accepted, the ``--i-know-this-destroys-data``
    confirmation is required, and the target must pass
    :func:`ensure_disposable_reset_target` — all before any connection.
    """
    if reset:
        url = explicit_url or environ.get("TEST_DATABASE_URL")
        if not url:
            raise HarnessError(
                "--reset-corpus is destructive and NEVER falls back to"
                " FEL_DATABASE_URL. Set TEST_DATABASE_URL (a disposable test"
                " database) or pass --database-url explicitly."
            )
        if not confirmed:
            raise HarnessError(
                "--reset-corpus additionally requires --i-know-this-destroys-data:"
                " it deletes every corpus + queue row in the target database."
            )
        ensure_disposable_reset_target(url, environ)
        return url
    url = explicit_url or environ.get("TEST_DATABASE_URL") or environ.get("FEL_DATABASE_URL")
    if not url:
        raise HarnessError("--database-url (or TEST_DATABASE_URL/FEL_DATABASE_URL) is required")
    return url


# ---------------------------------------------------------------------------
# Cohort + reset.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cohort:
    path: pathlib.Path
    sha256: str
    as_of: str
    issuers: tuple[dict[str, str], ...]


def load_cohort(path: pathlib.Path) -> Cohort:
    """Read the canonical issuer cohort (read-only; never modified)."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    issuers = tuple(
        {"ticker": str(i["ticker"]), "cik": str(i["cik"]), "name": str(i["name"])}
        for i in payload["issuers"]
    )
    if not issuers:
        raise HarnessError(f"cohort {path} lists no issuers")
    return Cohort(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        as_of=str(payload.get("as_of", "")),
        issuers=issuers,
    )


def reset_corpus(conn: psycopg.Connection[Any]) -> None:
    """Empty the corpus + job tables (DISPOSABLE databases only; the guards
    in :func:`resolve_database_url` / :func:`run_corpus_qa` run first)."""
    for statement in _RESET_STATEMENTS:
        conn.execute(statement)


# ---------------------------------------------------------------------------
# Run execution: expected set, enqueue, drain, per-job terminal outcomes.
# ---------------------------------------------------------------------------


def expected_filings(
    sec: SecClient, issuer: RunIssuer, forms: tuple[str, ...] | None
) -> tuple[FilingRef, ...]:
    """List the filings THIS run expects for one issuer.

    Uses the same submissions index + filter the pipeline's discovery
    handler uses, so the expected accession set and the enqueued fetch
    jobs are derived from identical inputs. (In live mode this costs one
    extra submissions request per issuer, within fair-access limits.)
    """
    form_filter = frozenset(forms) if forms is not None else None
    return tuple(discover_filings(sec, issuer.db_cik, forms=form_filter))


def enqueue_discovery(
    conn: psycopg.Connection[Any],
    issuers: Sequence[RunIssuer],
    *,
    run_id: str,
    forms: tuple[str, ...] | None = None,
    queue_name: str = DEFAULT_QUEUE,
) -> list[str]:
    """Enqueue one discovery job per issuer; returns the job ids.

    The idempotency key is RUN-SCOPED so every harness run re-executes
    discovery (fetch jobs still deduplicate per accession downstream in
    the pipeline's own discovery handler).
    """
    job_ids = []
    for issuer in issuers:
        payload: dict[str, object] = {"cik": issuer.db_cik}
        if forms is not None:
            payload["forms"] = list(forms)
        job_ids.append(
            queue.enqueue(
                conn,
                kind=JOB_KIND_SEC_DISCOVERY,
                payload=payload,
                queue=queue_name,
                idempotency_key=f"corpus-qa|{run_id}|discovery|{issuer.db_cik}",
            )
        )
    return job_ids


@dataclass(frozen=True)
class JobsSummary:
    """Terminal outcomes of every job THIS run expected (queryable jobs
    table), plus the queue backlog left after the iteration budget."""

    discovery_expected: int
    fetch_expected: int
    terminal_counts: dict[str, int]
    pending: int
    missing_accessions: tuple[str, ...]
    backlog_after_run: int
    failures: tuple[dict[str, Any], ...]

    def as_report_field(self) -> dict[str, Any]:
        return {
            "discovery_expected": self.discovery_expected,
            "fetch_expected": self.fetch_expected,
            "terminal_counts": dict(sorted(self.terminal_counts.items())),
            "pending": self.pending,
            "missing_fetch_jobs": list(self.missing_accessions),
            "backlog_after_run": self.backlog_after_run,
            "failures": list(self.failures),
        }


def _job_error_message(error: object) -> str | None:
    if isinstance(error, dict):
        inner = error.get("error")
        if isinstance(inner, dict) and "message" in inner:
            return str(inner["message"])
    return None if error is None else str(error)


def collect_job_outcomes(
    conn: psycopg.Connection[Any],
    *,
    discovery_job_ids: Sequence[str],
    expected_accessions: Sequence[str],
    queue_name: str = DEFAULT_QUEUE,
) -> JobsSummary:
    """Record the terminal state of every job this run expected."""
    fetch_keys = {f"sec-fetch|{accession}": accession for accession in expected_accessions}
    with conn.cursor(row_factory=dict_row) as cur:
        rows = list(cur.execute(_JOBS_BY_ID_SQL, (list(discovery_job_ids),)).fetchall())
        fetch_rows = list(
            cur.execute(
                _FETCH_JOBS_BY_KEY_SQL, (JOB_KIND_SEC_FILING_FETCH, list(fetch_keys))
            ).fetchall()
        )
        backlog_row = cur.execute(_QUEUE_BACKLOG_SQL, (queue_name,)).fetchone()
    rows.extend(fetch_rows)
    counts: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    pending = 0
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
        if status in _PENDING_STATUSES:
            pending += 1
        if status != "succeeded":
            payload = row["payload"] if isinstance(row["payload"], dict) else {}
            failures.append(
                {
                    "job_id": row["id"],
                    "kind": row["kind"],
                    "status": status,
                    "accession": payload.get("accession"),
                    "cik": payload.get("cik"),
                    "error": _job_error_message(row["error"]),
                }
            )
    found_keys = {str(row["idempotency_key"]) for row in fetch_rows}
    missing = tuple(accession for key, accession in fetch_keys.items() if key not in found_keys)
    return JobsSummary(
        discovery_expected=len(discovery_job_ids),
        fetch_expected=len(fetch_keys),
        terminal_counts=counts,
        pending=pending,
        missing_accessions=missing,
        backlog_after_run=int(backlog_row["n"]) if backlog_row is not None else 0,
        failures=tuple(failures),
    )


def run_failure_reasons(jobs: JobsSummary, *, queue_name: str = DEFAULT_QUEUE) -> list[str]:
    """Reasons this run FAILED (nonzero exit): a returning ``run_worker``
    proves nothing — only all-expected-jobs-succeeded and a drained queue do."""
    reasons = []
    if jobs.failures:
        statuses = sorted({str(f["status"]) for f in jobs.failures})
        reasons.append(
            f"{len(jobs.failures)} expected job(s) did not reach status"
            f" 'succeeded' (statuses: {', '.join(statuses)})"
        )
    if jobs.missing_accessions:
        reasons.append(
            f"{len(jobs.missing_accessions)} discovered filing(s) have no"
            " fetch job in the queue (never enqueued)"
        )
    if jobs.backlog_after_run:
        reasons.append(
            f"{jobs.backlog_after_run} job(s) still queued/claimed/running in"
            f" queue {queue_name!r} after the run — the iteration budget was"
            " exhausted before the queue drained"
        )
    return reasons


# ---------------------------------------------------------------------------
# Metrics (strictly over THIS run's entity + accession set).
# ---------------------------------------------------------------------------


def _verify_spans(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    entity_id: str,
    accessions: Sequence[str],
) -> tuple[int, int]:
    """Re-verify every persisted span hash against the canonical text the
    pipeline stored, over this run's versions only. Returns (total, verified)."""
    total = 0
    verified = 0
    with conn.cursor(row_factory=dict_row) as cur:
        versions = cur.execute(_ISSUER_TEXT_KEYS_SQL, (entity_id, list(accessions))).fetchall()
        for version in versions:
            text = storage.get(str(version["canonical_text_key"])).decode()
            spans = cur.execute(_VERSION_SPANS_SQL, (version["version_id"],)).fetchall()
            for span in spans:
                total += 1
                covered = text[span["start_char"] : span["end_char"]]
                expected = "sha256:" + hashlib.sha256(covered.encode()).hexdigest()
                if span["text_hash"] == expected:
                    verified += 1
    return total, verified


def _rate(verified: int, total: int) -> str:
    """Exact decimal-string rate; an empty denominator is UNAVAILABLE,
    never silently perfect."""
    if total == 0:
        return RATE_UNAVAILABLE
    return str((Decimal(verified) / Decimal(total)).quantize(Decimal("0.000001")))


def _count(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(sql, params).fetchone()
    return int(row["n"]) if row is not None else 0


def issuer_metrics(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    issuer: RunIssuer,
    accessions: Sequence[str],
) -> dict[str, Any]:
    """Corpus-quality metrics for one issuer over THIS run's accessions."""
    entity_id = issuer.entity_id
    scoped = (entity_id, list(accessions))
    with conn.cursor(row_factory=dict_row) as cur:
        facts = cur.execute(_ISSUER_FACTS_SQL, scoped).fetchone()
        reasons = cur.execute(_ISSUER_QUARANTINE_REASONS_SQL, (list(accessions),)).fetchall()
    if facts is None:  # pragma: no cover — count() always returns a row
        raise HarnessError(f"fact metrics query returned no row for {entity_id}")
    spans_total, spans_verified = _verify_spans(conn, storage, entity_id, accessions)
    return {
        "ticker": issuer.ticker,
        "cik": issuer.cik,
        "entity_id": entity_id,
        "expected_documents": len(accessions),
        "documents_ingested": _count(conn, _ISSUER_DOCUMENTS_SQL, scoped),
        "documents_parsed": _count(conn, _ISSUER_PARSED_SQL, scoped),
        "documents_quarantined": _count(conn, _ISSUER_QUARANTINED_SQL, (list(accessions),)),
        "document_versions_parsed": _count(conn, _ISSUER_VERSIONS_SQL, scoped),
        "facts_total": int(facts["total"]),
        "facts_canonical": int(facts["canonical"]),
        "facts_duplicate": int(facts["duplicate"]),
        "facts_restated": int(facts["restated"]),
        "spans_total": spans_total,
        "spans_verified": spans_verified,
        "span_hash_verification_rate": _rate(spans_verified, spans_total),
        "quarantine_reasons": {str(row["reason_code"]): int(row["n"]) for row in reasons},
    }


_SUMMED_FIELDS = (
    "expected_documents",
    "documents_ingested",
    "documents_parsed",
    "documents_quarantined",
    "document_versions_parsed",
    "facts_total",
    "facts_canonical",
    "facts_duplicate",
    "facts_restated",
    "spans_total",
    "spans_verified",
)


def evaluate_acceptance(
    mode: str,
    issuer_rows: Sequence[dict[str, Any]],
    totals: dict[str, Any],
    failure_reasons: Sequence[str],
) -> dict[str, Any]:
    """Acceptance gate: `accepted` is True only for a LIVE run in which
    every job succeeded, every expected issuer has at least one
    successfully parsed document, and evidence (spans) was produced."""
    reasons = []
    if mode == "synthetic":
        reasons.append(ACCEPTANCE_DEFERRED_LIVE_REASON)
    reasons.extend(failure_reasons)
    unparsed = [str(row["ticker"]) for row in issuer_rows if int(row["documents_parsed"]) < 1]
    if unparsed:
        reasons.append("issuer(s) without a successfully parsed document: " + ", ".join(unparsed))
    if int(totals["spans_total"]) == 0:
        reasons.append(
            "zero-evidence run: no source spans were persisted;"
            " span_hash_verification_rate is unavailable"
        )
    return {"accepted": not reasons, "reasons": reasons}


def build_report(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    cohort: Cohort,
    issuers: Sequence[RunIssuer],
    expected: Mapping[str, tuple[FilingRef, ...]],
    *,
    mode: str,
    label: str,
    run_id: str,
    jobs_completed: int,
    jobs: JobsSummary,
    failure_reasons: Sequence[str],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    rows = [
        issuer_metrics(conn, storage, issuer, [ref.accession for ref in expected[issuer.db_cik]])
        for issuer in issuers
    ]
    totals: dict[str, Any] = {field: sum(r[field] for r in rows) for field in _SUMMED_FIELDS}
    totals["span_hash_verification_rate"] = _rate(
        int(totals["spans_verified"]), int(totals["spans_total"])
    )
    distribution: dict[str, int] = {}
    for row in rows:
        for reason, count in row["quarantine_reasons"].items():
            distribution[reason] = distribution.get(reason, 0) + count
    totals["quarantine_reason_distribution"] = dict(sorted(distribution.items()))
    stamp = generated_at if generated_at is not None else datetime.now(UTC)
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": mode,
        "label": label,
        "generated_at": stamp.isoformat(),
        "provenance_note": SYNTHETIC_NOTE if mode == "synthetic" else LIVE_NOTE,
        "run": {
            "run_id": run_id,
            "mode": mode,
            "as_of": cohort.as_of,
            "identity_namespace": (
                SYNTHETIC_IDENTITY_NAMESPACE if mode == "synthetic" else LIVE_IDENTITY_NAMESPACE
            ),
            "expected_issuers": [issuer.ticker for issuer in issuers],
        },
        "acceptance": evaluate_acceptance(mode, rows, totals, failure_reasons),
        "cohort": {
            "path": "evals/datasets/issuer-cohort.json",
            "sha256": cohort.sha256,
            "as_of": cohort.as_of,
            "issuer_count": len(cohort.issuers),
        },
        "pipeline": {
            "parser_version": PARSER_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
            "queue": DEFAULT_QUEUE,
            "jobs_completed": jobs_completed,
            "jobs": jobs.as_report_field(),
        },
        "issuers": rows,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# Validation + persistence.
# ---------------------------------------------------------------------------


def _validate_rate(entry: dict[str, Any], where: str) -> None:
    rate = entry.get("span_hash_verification_rate")
    if int(entry["spans_total"]) == 0:
        if rate != RATE_UNAVAILABLE:
            raise HarnessError(
                f"{where}: span_hash_verification_rate must be"
                f" {RATE_UNAVAILABLE!r} when spans_total is 0, got {rate!r}"
            )
    elif rate == RATE_UNAVAILABLE:
        raise HarnessError(f"{where}: rate is {RATE_UNAVAILABLE!r} but spans_total is nonzero")


def _validate_issuer_provenance(mode: str, issuer: dict[str, Any]) -> None:
    ticker = str(issuer["ticker"])
    cohort_entity = entity_id_for_cik(str(issuer["cik"]))
    if mode == "synthetic":
        expected = synthetic_entity_id(ticker)
        if issuer["entity_id"] != expected or issuer["entity_id"] == cohort_entity:
            raise HarnessError(
                f"provenance violation: synthetic issuer {ticker} must be keyed"
                f" by the namespaced synthetic entity id {expected}, got"
                f" {issuer['entity_id']!r}"
            )
    elif issuer["entity_id"] != cohort_entity:
        raise HarnessError(
            f"provenance violation: live issuer {ticker} must be keyed by the"
            f" cohort CIK entity id {cohort_entity}, got {issuer['entity_id']!r}"
        )


def validate_report(report: dict[str, Any]) -> None:
    """Structural + provenance validation of corpus-qa-report/v1 (fails
    closed): mixed or ambiguous synthetic/live provenance is rejected."""
    if report.get("schema") != REPORT_SCHEMA:
        raise HarnessError(f"unexpected schema {report.get('schema')!r}")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise HarnessError(f"unexpected schema_version {report.get('schema_version')!r}")
    mode = report.get("mode")
    if mode not in ("synthetic", "live"):
        raise HarnessError(f"mode must be synthetic|live, got {mode!r}")
    for key in ("label", "generated_at", "provenance_note", "cohort", "pipeline"):
        if key not in report:
            raise HarnessError(f"report is missing {key!r}")
    run = report.get("run")
    if not isinstance(run, dict):
        raise HarnessError("report is missing the 'run' provenance object")
    for key in ("run_id", "mode", "as_of", "identity_namespace", "expected_issuers"):
        if key not in run:
            raise HarnessError(f"run provenance is missing {key!r}")
    if run["mode"] != mode:
        raise HarnessError(f"mixed provenance: run.mode {run['mode']!r} != report mode {mode!r}")
    expected_namespace = (
        SYNTHETIC_IDENTITY_NAMESPACE if mode == "synthetic" else LIVE_IDENTITY_NAMESPACE
    )
    if run["identity_namespace"] != expected_namespace:
        raise HarnessError(
            f"mixed provenance: identity_namespace {run['identity_namespace']!r}"
            f" does not match mode {mode!r} (expected {expected_namespace!r})"
        )
    issuers = report.get("issuers")
    totals = report.get("totals")
    if not isinstance(issuers, list) or not issuers:
        raise HarnessError("report has no issuers")
    if not isinstance(totals, dict):
        raise HarnessError("report has no totals")
    if list(run["expected_issuers"]) != [issuer["ticker"] for issuer in issuers]:
        raise HarnessError("run.expected_issuers does not match the measured issuer set")
    acceptance = report.get("acceptance")
    if not isinstance(acceptance, dict) or not isinstance(acceptance.get("accepted"), bool):
        raise HarnessError("report is missing an 'acceptance' object with a boolean 'accepted'")
    reasons = acceptance.get("reasons")
    if not isinstance(reasons, list):
        raise HarnessError("acceptance.reasons must be a list")
    if acceptance["accepted"] and reasons:
        raise HarnessError("an accepted report must not carry acceptance reasons")
    if not acceptance["accepted"] and not reasons:
        raise HarnessError("a non-accepted report must state its acceptance reasons")
    if mode == "synthetic" and acceptance["accepted"]:
        raise HarnessError(
            "a synthetic report can never be acceptance-grade: T0112 acceptance"
            " requires the live cohort run"
        )
    pipeline = report["pipeline"]
    if not isinstance(pipeline, dict) or not isinstance(pipeline.get("jobs"), dict):
        raise HarnessError("pipeline.jobs (per-job terminal outcomes) is missing")
    for key in ("terminal_counts", "pending", "missing_fetch_jobs", "failures"):
        if key not in pipeline["jobs"]:
            raise HarnessError(f"pipeline.jobs is missing {key!r}")
    for issuer in issuers:
        for field in (
            "ticker",
            "cik",
            "entity_id",
            *_SUMMED_FIELDS,
            "span_hash_verification_rate",
            "quarantine_reasons",
        ):
            if field not in issuer:
                raise HarnessError(f"issuer entry is missing {field!r}: {issuer}")
        _validate_issuer_provenance(mode, issuer)
        _validate_rate(issuer, f"issuer {issuer['ticker']}")
    for field in (*_SUMMED_FIELDS, "span_hash_verification_rate", "quarantine_reason_distribution"):
        if field not in totals:
            raise HarnessError(f"totals is missing {field!r}")
    for field in _SUMMED_FIELDS:
        if totals[field] != sum(issuer[field] for issuer in issuers):
            raise HarnessError(f"totals[{field!r}] does not equal the issuer sum")
    _validate_rate(totals, "totals")
    if mode == "synthetic" and "SYNTHETIC" not in str(report["provenance_note"]):
        raise HarnessError("synthetic reports must carry the synthetic provenance note")


def write_report(report: dict[str, Any], reports_dir: pathlib.Path) -> pathlib.Path:
    validate_report(report)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report['label']}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """Outcome of one harness pass. ``failed`` means the run itself failed
    (jobs failed/pending/missing, or the iteration budget was exhausted);
    the report is still written, marked non-acceptance."""

    path: pathlib.Path
    report: dict[str, Any]
    failed: bool
    failure_reasons: tuple[str, ...]


def run_corpus_qa(
    *,
    mode: str,
    database_url: str,
    reports_dir: pathlib.Path,
    label: str,
    cohort_path: pathlib.Path = DEFAULT_COHORT_PATH,
    storage_dir: pathlib.Path | None = None,
    forms: tuple[str, ...] | None = None,
    reset: bool = False,
    generated_at: datetime | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> RunResult:
    """Run one full harness pass and return the written report + outcome.

    All fail-closed gates run BEFORE any connection or network access:
    mode validation, the destructive-reset disposability check, and (live
    mode) the FEL_SEC_USER_AGENT identity requirement.
    """
    if mode not in ("synthetic", "live"):
        raise HarnessError(f"unknown mode {mode!r}")
    cohort = load_cohort(cohort_path)
    issuers = run_issuers(cohort, mode)
    if reset:
        ensure_disposable_reset_target(database_url)
    storage: StorageProvider
    sec: SecClient
    if mode == "synthetic":
        # A storage dir makes blobs durable across harness reruns (a rerun
        # is a corpus no-op that writes nothing, so span re-verification
        # needs the first run's canonical texts); without one, an
        # in-memory store covers a single-pass run.
        storage = (
            LocalDirStorageProvider(storage_dir)
            if storage_dir is not None
            else MockStorageProvider()
        )
        sec = SyntheticCohortSecClient([issuer.db_cik for issuer in issuers])
        # Synthetic submissions carry every planned form; no filter needed.
        effective_forms = forms
    else:
        if storage_dir is None:
            raise HarnessError("live mode requires --storage-dir (durable blob store)")
        user_agent = require_live_sec_user_agent()
        from fel_workers.ingestion.sec_client import LiveSecClient

        storage = LocalDirStorageProvider(storage_dir)
        sec = LiveSecClient(user_agent=user_agent)
        effective_forms = forms if forms is not None else DEFAULT_LIVE_FORMS

    run_id = uuid.uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as conn:
        if reset:
            reset_corpus(conn)
        expected = {
            issuer.db_cik: expected_filings(sec, issuer, effective_forms) for issuer in issuers
        }
        discovery_job_ids = enqueue_discovery(conn, issuers, run_id=run_id, forms=effective_forms)
        jobs_completed = run_worker(
            conn, storage, sec, queue_name=DEFAULT_QUEUE, max_iterations=max_iterations
        )
        jobs = collect_job_outcomes(
            conn,
            discovery_job_ids=discovery_job_ids,
            expected_accessions=[ref.accession for refs in expected.values() for ref in refs],
        )
        failure_reasons = run_failure_reasons(jobs)
        report = build_report(
            conn,
            storage,
            cohort,
            issuers,
            expected,
            mode=mode,
            label=label,
            run_id=run_id,
            jobs_completed=jobs_completed,
            jobs=jobs,
            failure_reasons=failure_reasons,
            generated_at=generated_at,
        )
    path = write_report(report, reports_dir)
    return RunResult(
        path=path,
        report=report,
        failed=bool(failure_reasons),
        failure_reasons=tuple(failure_reasons),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "live"), default="synthetic")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL with db/migrations 0001+0002 applied (default:"
        " $TEST_DATABASE_URL, then $FEL_DATABASE_URL; with --reset-corpus the"
        " FEL_DATABASE_URL fallback is NEVER used)",
    )
    parser.add_argument("--reports-dir", type=pathlib.Path, required=True)
    parser.add_argument("--label", required=True, help="report label; the file is <label>.json")
    parser.add_argument("--cohort", type=pathlib.Path, default=DEFAULT_COHORT_PATH)
    parser.add_argument(
        "--storage-dir",
        type=pathlib.Path,
        default=None,
        help="durable blob root (required for live mode; optional for "
        "synthetic reruns against a persistent database)",
    )
    parser.add_argument(
        "--forms",
        default=None,
        help="comma-separated form filter for discovery (live default: 10-K,10-Q,10-Q/A)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help="consumer claim-attempt budget; an undrained queue is a run failure",
    )
    parser.add_argument(
        "--reset-corpus",
        action="store_true",
        help="DESTRUCTIVE: empty corpus+jobs tables first. Requires"
        " --i-know-this-destroys-data, uses only TEST_DATABASE_URL or an"
        " explicit --database-url (never FEL_DATABASE_URL), and refuses"
        " database names not ending in '_test' unless"
        " FEL_HARNESS_ALLOW_RESET=1",
    )
    parser.add_argument(
        "--i-know-this-destroys-data",
        action="store_true",
        dest="destroy_confirmed",
        help="explicit confirmation required by --reset-corpus",
    )
    args = parser.parse_args(argv)
    forms = tuple(f.strip() for f in args.forms.split(",")) if args.forms else None
    try:
        database_url = resolve_database_url(
            reset=args.reset_corpus,
            explicit_url=args.database_url,
            confirmed=args.destroy_confirmed,
        )
        result = run_corpus_qa(
            mode=args.mode,
            database_url=database_url,
            reports_dir=args.reports_dir,
            label=args.label,
            cohort_path=args.cohort,
            storage_dir=args.storage_dir,
            forms=forms,
            reset=args.reset_corpus,
            max_iterations=args.max_iterations,
        )
    except HarnessError as exc:
        print(f"corpus-qa: {exc}", file=sys.stderr)  # noqa: T201 — operator-facing CLI
        return 2
    print(f"wrote {result.path}")  # noqa: T201 — operator-facing CLI
    if result.failed:
        for reason in result.failure_reasons:
            print(f"corpus-qa: RUN FAILURE: {reason}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
