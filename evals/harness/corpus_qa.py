"""T0112: benchmark-cohort ingestion harness + corpus-quality metrics.

Reads the canonical cohort ``evals/datasets/issuer-cohort.json`` (read
only), drives discovery -> fetch -> ingest through the REAL job consumer
(``fel_workers.consumer.run_worker``) against a real Postgres, then
computes corpus-quality metrics and records them to a versioned JSON
report under ``evals/reports/corpus-qa/``. Schema:
``evals/reports/corpus-qa/SCHEMA.md`` (contract corpus-qa-report/v1).

Synthetic mode (default; NO network):

    TEST_DATABASE_URL="postgresql://..." \\
    PYTHONPATH=evals:workers/src:packages/providers:apps/api \\
    .venv/bin/python -m harness.corpus_qa \\
        --mode synthetic --reset-corpus \\
        --reports-dir evals/reports/corpus-qa --label <date>-synthetic-cohort

Live mode (SEC egress + fair-access compliance REQUIRED; never run from
CI or an egress-blocked session):

    FEL_DATABASE_URL="postgresql://..." \\
    PYTHONPATH=evals:workers/src:packages/providers:apps/api \\
    .venv/bin/python -m harness.corpus_qa \\
        --mode live --storage-dir /var/fel/storage \\
        --forms 10-K,10-Q,10-Q/A \\
        --reports-dir evals/reports/corpus-qa --label <date>-live-cohort

Metrics are computed from the corpus tables the pipeline itself wrote:
documents ingested/parsed/quarantined per issuer, fact totals with
duplicate and restatement linkage counts, span text-hash re-verification
rate against the persisted canonical text, and the quarantine reason-code
distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fel_providers.interfaces import SecClient, StorageProvider
from fel_providers.mocks import MockStorageProvider
from fel_workers import queue
from fel_workers.consumer import entity_id_for_cik, run_worker
from fel_workers.ingestion.discovery import JOB_KIND_SEC_DISCOVERY
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

SYNTHETIC_NOTE = (
    "SYNTHETIC RUN: the pipeline, queue, quarantine, and metrics paths are "
    "real, but every ingested byte was generated from committed synthetic "
    "templates (evals/datasets/synthetic-corpus/). Cohort tickers/CIKs key "
    "the benchmark slots only — NO metric in this report describes any real "
    "company's filings."
)
LIVE_NOTE = (
    "LIVE RUN: documents were fetched from SEC EDGAR under the fair-access "
    "policy via the frozen LiveSecClient."
)

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

_ISSUER_DOCUMENTS_SQL = "SELECT count(*) AS n FROM documents WHERE entity_id = %s"
_ISSUER_PARSED_SQL = """
    SELECT count(*) AS n FROM documents d
    WHERE d.entity_id = %s AND EXISTS (
        SELECT 1 FROM document_versions dv
        WHERE dv.document_id = d.id AND dv.status = 'parsed'
    )
"""
_ISSUER_VERSIONS_SQL = """
    SELECT count(*) AS n FROM document_versions dv
    JOIN documents d ON d.id = dv.document_id
    WHERE d.entity_id = %s AND dv.status = 'parsed'
"""
_ISSUER_QUARANTINED_SQL = """
    SELECT count(DISTINCT q.accession) AS n FROM ingestion_quarantine q
    JOIN documents d ON d.accession = q.accession
    WHERE d.entity_id = %s
"""
_ISSUER_FACTS_SQL = """
    SELECT count(*) AS total,
           count(*) FILTER (WHERE duplicate_of IS NULL) AS canonical,
           count(*) FILTER (WHERE duplicate_of IS NOT NULL) AS duplicate,
           count(*) FILTER (WHERE restates IS NOT NULL) AS restated
    FROM financial_facts WHERE entity_id = %s
"""
_ISSUER_QUARANTINE_REASONS_SQL = """
    SELECT q.reason_code, count(*) AS n FROM ingestion_quarantine q
    JOIN documents d ON d.accession = q.accession
    WHERE d.entity_id = %s
    GROUP BY q.reason_code ORDER BY q.reason_code
"""
_ISSUER_TEXT_KEYS_SQL = """
    SELECT dv.id::text AS version_id, dv.canonical_text_key
    FROM document_versions dv
    JOIN documents d ON d.id = dv.document_id
    WHERE d.entity_id = %s AND dv.status = 'parsed'
    ORDER BY dv.id
"""
_VERSION_SPANS_SQL = """
    SELECT start_char, end_char, text_hash FROM source_spans
    WHERE document_version_id = %s ORDER BY start_char, end_char
"""


class HarnessError(Exception):
    """The harness was misconfigured or a run invariant failed."""


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
    """Empty the corpus + job tables (DISPOSABLE databases only)."""
    for statement in _RESET_STATEMENTS:
        conn.execute(statement)


def run_ingestion(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    sec: SecClient,
    cohort: Cohort,
    *,
    forms: tuple[str, ...] | None = None,
    queue_name: str = DEFAULT_QUEUE,
    max_iterations: int = 10_000,
) -> int:
    """Enqueue one discovery job per issuer and drain the queue through the
    REAL consumer. Returns the number of jobs completed."""
    for issuer in cohort.issuers:
        payload: dict[str, object] = {"cik": issuer["cik"]}
        if forms is not None:
            payload["forms"] = list(forms)
        queue.enqueue(
            conn,
            kind=JOB_KIND_SEC_DISCOVERY,
            payload=payload,
            queue=queue_name,
            idempotency_key=f"corpus-qa-discovery|{issuer['cik']}",
        )
    return run_worker(conn, storage, sec, queue_name=queue_name, max_iterations=max_iterations)


def _verify_spans(
    conn: psycopg.Connection[Any], storage: StorageProvider, entity_id: str
) -> tuple[int, int]:
    """Re-verify every persisted span hash against the canonical text the
    pipeline stored. Returns (total, verified)."""
    total = 0
    verified = 0
    with conn.cursor(row_factory=dict_row) as cur:
        versions = cur.execute(_ISSUER_TEXT_KEYS_SQL, (entity_id,)).fetchall()
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
    """Exact decimal-string rate (never a binary float)."""
    if total == 0:
        return "1"
    return str((Decimal(verified) / Decimal(total)).quantize(Decimal("0.000001")))


def _count(conn: psycopg.Connection[Any], sql: str, entity_id: str) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(sql, (entity_id,)).fetchone()
    return int(row["n"]) if row is not None else 0


def issuer_metrics(
    conn: psycopg.Connection[Any], storage: StorageProvider, issuer: dict[str, str]
) -> dict[str, Any]:
    entity_id = entity_id_for_cik(issuer["cik"])
    with conn.cursor(row_factory=dict_row) as cur:
        facts = cur.execute(_ISSUER_FACTS_SQL, (entity_id,)).fetchone()
        reasons = cur.execute(_ISSUER_QUARANTINE_REASONS_SQL, (entity_id,)).fetchall()
    if facts is None:  # pragma: no cover — count() always returns a row
        raise HarnessError(f"fact metrics query returned no row for {entity_id}")
    spans_total, spans_verified = _verify_spans(conn, storage, entity_id)
    return {
        "ticker": issuer["ticker"],
        "cik": issuer["cik"],
        "entity_id": entity_id,
        "documents_ingested": _count(conn, _ISSUER_DOCUMENTS_SQL, entity_id),
        "documents_parsed": _count(conn, _ISSUER_PARSED_SQL, entity_id),
        "documents_quarantined": _count(conn, _ISSUER_QUARANTINED_SQL, entity_id),
        "document_versions_parsed": _count(conn, _ISSUER_VERSIONS_SQL, entity_id),
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


def build_report(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    cohort: Cohort,
    *,
    mode: str,
    label: str,
    jobs_completed: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    issuers = [issuer_metrics(conn, storage, issuer) for issuer in cohort.issuers]
    totals: dict[str, Any] = {field: sum(i[field] for i in issuers) for field in _SUMMED_FIELDS}
    totals["span_hash_verification_rate"] = _rate(
        int(totals["spans_verified"]), int(totals["spans_total"])
    )
    distribution: dict[str, int] = {}
    for issuer in issuers:
        for reason, count in issuer["quarantine_reasons"].items():
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
        },
        "issuers": issuers,
        "totals": totals,
    }


def validate_report(report: dict[str, Any]) -> None:
    """Structural validation of contract corpus-qa-report/v1 (fails closed)."""
    if report.get("schema") != REPORT_SCHEMA:
        raise HarnessError(f"unexpected schema {report.get('schema')!r}")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise HarnessError(f"unexpected schema_version {report.get('schema_version')!r}")
    if report.get("mode") not in ("synthetic", "live"):
        raise HarnessError(f"mode must be synthetic|live, got {report.get('mode')!r}")
    for key in ("label", "generated_at", "provenance_note", "cohort", "pipeline"):
        if key not in report:
            raise HarnessError(f"report is missing {key!r}")
    issuers = report.get("issuers")
    totals = report.get("totals")
    if not isinstance(issuers, list) or not issuers:
        raise HarnessError("report has no issuers")
    if not isinstance(totals, dict):
        raise HarnessError("report has no totals")
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
    for field in (*_SUMMED_FIELDS, "span_hash_verification_rate", "quarantine_reason_distribution"):
        if field not in totals:
            raise HarnessError(f"totals is missing {field!r}")
    for field in _SUMMED_FIELDS:
        if totals[field] != sum(issuer[field] for issuer in issuers):
            raise HarnessError(f"totals[{field!r}] does not equal the issuer sum")
    if report["mode"] == "synthetic" and "SYNTHETIC" not in str(report["provenance_note"]):
        raise HarnessError("synthetic reports must carry the synthetic provenance note")


def write_report(report: dict[str, Any], reports_dir: pathlib.Path) -> pathlib.Path:
    validate_report(report)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report['label']}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return path


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
) -> pathlib.Path:
    """Run one full harness pass and return the written report path."""
    cohort = load_cohort(cohort_path)
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
        sec = SyntheticCohortSecClient([issuer["cik"] for issuer in cohort.issuers])
        # Synthetic submissions carry every planned form; no filter needed.
        effective_forms = forms
    elif mode == "live":
        if storage_dir is None:
            raise HarnessError("live mode requires --storage-dir (durable blob store)")
        from fel_workers.ingestion.sec_client import LiveSecClient

        storage = LocalDirStorageProvider(storage_dir)
        sec = LiveSecClient()
        effective_forms = forms if forms is not None else DEFAULT_LIVE_FORMS
    else:
        raise HarnessError(f"unknown mode {mode!r}")

    with psycopg.connect(database_url, autocommit=True) as conn:
        if reset:
            reset_corpus(conn)
        jobs_completed = run_ingestion(conn, storage, sec, cohort, forms=effective_forms)
        report = build_report(
            conn,
            storage,
            cohort,
            mode=mode,
            label=label,
            jobs_completed=jobs_completed,
            generated_at=generated_at,
        )
    return write_report(report, reports_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "live"), default="synthetic")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL") or os.environ.get("FEL_DATABASE_URL"),
        help="Postgres URL with db/migrations 0001+0002 applied "
        "(default: $TEST_DATABASE_URL, then $FEL_DATABASE_URL)",
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
        "--reset-corpus",
        action="store_true",
        help="empty corpus+jobs tables first (DISPOSABLE databases only)",
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url (or TEST_DATABASE_URL/FEL_DATABASE_URL) is required")
    forms = tuple(f.strip() for f in args.forms.split(",")) if args.forms else None
    path = run_corpus_qa(
        mode=args.mode,
        database_url=args.database_url,
        reports_dir=args.reports_dir,
        label=args.label,
        cohort_path=args.cohort,
        storage_dir=args.storage_dir,
        forms=forms,
        reset=args.reset_corpus,
    )
    print(f"wrote {path}")  # noqa: T201 — operator-facing CLI
    return 0


if __name__ == "__main__":
    sys.exit(main())
