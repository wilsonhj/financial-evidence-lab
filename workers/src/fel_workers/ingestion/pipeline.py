"""Idempotent, versioned ingestion jobs + atomic corpus publication (T0105)
and quarantine of malformed sources (T0106).

The job key is derived from (entity, accession, source hash, parser
version, normalizer version) per spec 12.4: re-running an identical job
returns the recorded result and performs no writes; bumping either version
creates a new derived document version without mutating the source. The
entity/accession components keep byte-identical filings under different
accessions distinct — each gets its own document and version rows.

Concurrency: the ingestion-run ledger row is CLAIMED up front
(``INSERT .. ON CONFLICT DO NOTHING RETURNING``) inside the job
transaction, so of two racing identical jobs exactly one does the work; the
loser blocks on the claim until the winner commits, then replays the
recorded result. No unique violation can escape the idempotency path.

Divergence policy (see raw_store): a re-fetch of a known accession with
different bytes fails closed into quarantine with reason code
``DIVERGENT_ACCESSION_CONTENT`` — evidence is immutable, and
``documents.content_hash`` always matches the bytes the published versions
were parsed from.

Corpus versions are published atomically — a single transaction flips the
active pointer, and a partial unique index guarantees at most one active
version even under races; a losing racer gets :class:`PublishConflictError`
instead of a raw database error.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fel_providers.interfaces import StorageProvider
from fel_workers.ingestion.errors import DivergentAccessionError, IngestError
from fel_workers.ingestion.parser import PARSER_VERSION, parse_filing
from fel_workers.ingestion.raw_store import (
    StoredDocument,
    content_address,
    document_id_for_accession,
    store_raw_document,
)
from fel_workers.ingestion.xbrl import NORMALIZER_VERSION, PriorFact, normalize_facts


class PublishConflictError(Exception):
    """A concurrent publisher activated another corpus version first.

    The demote-promote transaction lost the race on the single-active
    partial unique index; the caller may re-read the active pointer and
    retry against the new state.
    """


def job_key(
    source_hash: str,
    parser_version: str,
    normalizer_version: str,
    *,
    entity_id: str,
    accession: str,
) -> str:
    """Deterministic job identity per spec 12.4.

    Includes the entity and accession so byte-identical filings under a
    second accession/entity are distinct jobs (each produces its own
    document + version rows) instead of no-oping onto the first filing.
    """
    parts = (entity_id, accession, source_hash, parser_version, normalizer_version)
    for part in parts:
        # Inputs are uuid/accession/version strings, so '|' can never
        # appear; assert anyway so the delimiter stays unambiguous.
        if "|" in part:
            raise ValueError(f"job key component {part!r} contains the '|' delimiter")
    seed = "|".join(parts)
    return hashlib.sha256(seed.encode()).hexdigest()


@dataclass(frozen=True)
class IngestionOutcome:
    """Result of one ingestion job run."""

    status: str
    """'succeeded', 'quarantined', or 'noop' (identical job already ran)."""

    job_key: str
    document_id: str | None
    document_version_id: str | None
    sections: int = 0
    spans: int = 0
    tables: int = 0
    facts: int = 0
    reason_code: str | None = None
    diagnostic: str | None = None


def _prior_canonical_facts(
    conn: psycopg.Connection[Any], *, entity_id: str, published_before: datetime
) -> dict[str, PriorFact]:
    """Latest canonical fact per key from earlier published filings.

    Deterministic restatement targets: only the LATEST successfully parsed
    version of each prior document is consulted, and candidates are totally
    ordered (published_at DESC, version created_at DESC, fact id) so reruns
    always link ``restates`` to the same fact row.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            SELECT DISTINCT ON (ff.fact_key) ff.fact_key, ff.id, ff.value
            FROM financial_facts ff
            JOIN document_versions dv ON dv.id = ff.document_version_id
            JOIN documents d ON d.id = dv.document_id
            WHERE ff.entity_id = %s
              AND ff.duplicate_of IS NULL
              AND dv.status = 'parsed'
              AND d.published_at < %s
              AND dv.id = (
                  SELECT dv2.id FROM document_versions dv2
                  WHERE dv2.document_id = d.id AND dv2.status = 'parsed'
                  ORDER BY dv2.created_at DESC, dv2.id DESC
                  LIMIT 1
              )
            ORDER BY ff.fact_key, d.published_at DESC, dv.created_at DESC, ff.id
            """,
            (entity_id, published_before),
        ).fetchall()
    return {
        str(row["fact_key"]): PriorFact(fact_id=str(row["id"]), value=str(row["value"]))
        for row in rows
    }


def _noop_outcome(key: str, row: dict[str, Any]) -> IngestionOutcome:
    result = row["result"] if isinstance(row["result"], dict) else {}
    return IngestionOutcome(
        status="noop",
        job_key=key,
        document_id=str(row["document_id"]) if row["document_id"] is not None else None,
        document_version_id=(
            str(row["document_version_id"]) if row["document_version_id"] is not None else None
        ),
        sections=int(result.get("sections", 0)),
        spans=int(result.get("spans", 0)),
        tables=int(result.get("tables", 0)),
        facts=int(result.get("facts", 0)),
        reason_code=result.get("reason_code"),
        diagnostic=result.get("diagnostic"),
    )


def canonical_text_address(text: str) -> str:
    """Content-addressed storage key for a canonical parsed text rendering."""
    return f"text/sha256/{hashlib.sha256(text.encode()).hexdigest()}"


def ingest_filing(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    *,
    entity_id: str,
    accession: str,
    source_url: str,
    raw: bytes,
    published_at: datetime,
    form: str | None = None,
    filed_at: datetime | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    mime_type: str = "text/html",
) -> IngestionOutcome:
    """Run the full store -> parse -> normalize -> persist pipeline once.

    Idempotent: an identical (entity, accession, source, parser,
    normalizer) job is a no-op returning the recorded result — enforced by
    claiming the ledger row up front, so concurrent identical jobs converge
    on one worker doing the work. Malformed or divergent sources are
    quarantined with an actionable diagnostic instead of failing the job.
    """
    content_hash, storage_key = content_address(raw)
    key = job_key(
        content_hash,
        PARSER_VERSION,
        NORMALIZER_VERSION,
        entity_id=entity_id,
        accession=accession,
    )
    document_id = document_id_for_accession(accession)
    version_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://financial-evidence-lab.dev/version|{document_id}|{content_hash}"
            f"|{PARSER_VERSION}|{NORMALIZER_VERSION}",
        )
    )
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as run_cur:
            claimed = run_cur.execute(
                "INSERT INTO ingestion_runs (job_key, source_hash, parser_version,"
                " normalizer_version, status) VALUES (%s, %s, %s, %s, 'running')"
                " ON CONFLICT (job_key) DO NOTHING RETURNING job_key",
                (key, content_hash, PARSER_VERSION, NORMALIZER_VERSION),
            ).fetchone()
            if claimed is None:
                # Another (possibly concurrent) identical job holds or held
                # the claim; the ON CONFLICT path waits for its commit, so
                # this read observes the recorded terminal result.
                existing = run_cur.execute(
                    "SELECT job_key, document_id, document_version_id, status, result"
                    " FROM ingestion_runs WHERE job_key = %s",
                    (key,),
                ).fetchone()
                if existing is None or existing["status"] == "running":
                    raise RuntimeError(f"ingestion run {key} is claimed but has no terminal result")
                return _noop_outcome(key, dict(existing))

        stored: StoredDocument | None = None
        try:
            stored = store_raw_document(
                conn,
                storage,
                entity_id=entity_id,
                accession=accession,
                source_url=source_url,
                raw=raw,
                published_at=published_at,
                form=form,
                filed_at=filed_at,
                period_start=period_start,
                period_end=period_end,
                mime_type=mime_type,
                content_hash=content_hash,
                storage_key=storage_key,
            )
            parsed = parse_filing(raw, id_seed=version_id, content_hash=content_hash)
            prior = _prior_canonical_facts(conn, entity_id=entity_id, published_before=published_at)
            facts = normalize_facts(
                parsed,
                entity_id=entity_id,
                document_version_id=version_id,
                prior_facts=prior,
            )
        except IngestError as exc:
            if isinstance(exc, DivergentAccessionError):
                quarantine_document_id: str | None = exc.document_id
            elif stored is not None:
                quarantine_document_id = stored.document_id
            else:  # pragma: no cover — defensive
                quarantine_document_id = None
            _record_quarantine(
                conn,
                key=key,
                accession=accession,
                source_url=source_url,
                content_hash=content_hash,
                document_id=quarantine_document_id,
                reason_code=exc.reason_code,
                diagnostic=exc.diagnostic,
            )
            return IngestionOutcome(
                status="quarantined",
                job_key=key,
                document_id=quarantine_document_id,
                document_version_id=None,
                reason_code=exc.reason_code,
                diagnostic=exc.diagnostic,
            )

        # Persist the canonical text immutably so span offsets/text hashes
        # stay verifiable against exactly the bytes they were computed from.
        text_key = canonical_text_address(parsed.text)
        storage.put(text_key, parsed.text.encode())

        conn.execute(
            "INSERT INTO document_versions"
            " (id, document_id, parser_version, normalizer_version, status,"
            "  canonical_text_key)"
            " VALUES (%s, %s, %s, %s, 'parsed', %s)",
            (version_id, stored.document_id, PARSER_VERSION, NORMALIZER_VERSION, text_key),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO sections (id, document_version_id, parent_id, heading,"
                " heading_path, ord, start_char, end_char)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        section.id,
                        version_id,
                        section.parent_id,
                        section.heading,
                        list(section.heading_path),
                        section.order,
                        section.start_char,
                        section.end_char,
                    )
                    for section in parsed.sections
                ],
            )
            cur.executemany(
                "INSERT INTO source_spans (id, document_version_id, section_id,"
                " start_char, end_char, text_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (
                        span.id,
                        version_id,
                        span.section_id,
                        span.start_char,
                        span.end_char,
                        span.text_hash,
                    )
                    for span in parsed.spans
                ],
            )
            cur.executemany(
                "INSERT INTO tables_meta (id, document_version_id, section_id, ord,"
                " caption, headers, rows) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        table.id,
                        version_id,
                        table.section_id,
                        table.order,
                        table.caption,
                        json.dumps(list(table.headers)),
                        json.dumps([list(row) for row in table.rows]),
                    )
                    for table in parsed.tables
                ],
            )
            cur.executemany(
                """
                INSERT INTO financial_facts
                    (id, entity_id, document_version_id, concept, label, value,
                     unit, scale, period_type, period_instant, period_start,
                     period_end, dimensions, source_span_id, reported_or_derived,
                     confidence, duplicate_of, restates, fact_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                """,
                [
                    (
                        fact.id,
                        fact.entity_id,
                        fact.document_version_id,
                        fact.concept,
                        fact.label,
                        fact.value,
                        fact.unit,
                        fact.scale,
                        fact.period_type,
                        fact.period_instant,
                        fact.period_start,
                        fact.period_end,
                        json.dumps(dict(fact.dimensions)),
                        fact.source_span_id,
                        fact.reported_or_derived,
                        fact.confidence,
                        fact.duplicate_of,
                        fact.restates,
                        fact.fact_key,
                    )
                    for fact in facts
                ],
            )
        result = {
            "sections": len(parsed.sections),
            "spans": len(parsed.spans),
            "tables": len(parsed.tables),
            "facts": len(facts),
        }
        conn.execute(
            "UPDATE ingestion_runs SET status = 'succeeded', document_id = %s,"
            " document_version_id = %s, result = %s WHERE job_key = %s",
            (stored.document_id, version_id, json.dumps(result), key),
        )
        return IngestionOutcome(
            status="succeeded",
            job_key=key,
            document_id=stored.document_id,
            document_version_id=version_id,
            sections=len(parsed.sections),
            spans=len(parsed.spans),
            tables=len(parsed.tables),
            facts=len(facts),
        )


def _record_quarantine(
    conn: psycopg.Connection[Any],
    *,
    key: str,
    accession: str,
    source_url: str,
    content_hash: str,
    document_id: str | None,
    reason_code: str,
    diagnostic: str,
) -> None:
    conn.execute(
        "INSERT INTO ingestion_quarantine (id, accession, source_url, content_hash,"
        " reason_code, diagnostic, detail) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            str(uuid.uuid4()),
            accession,
            source_url,
            content_hash,
            reason_code,
            diagnostic,
            json.dumps({"job_key": key}),
        ),
    )
    conn.execute(
        "UPDATE ingestion_runs SET status = 'quarantined', document_id = %s,"
        " result = %s WHERE job_key = %s",
        (
            document_id,
            json.dumps({"reason_code": reason_code, "diagnostic": diagnostic}),
            key,
        ),
    )


def create_corpus_version(
    conn: psycopg.Connection[Any],
    *,
    label: str,
    document_version_ids: Sequence[str],
) -> str:
    """Create a draft corpus version over the given document versions."""
    corpus_version_id = str(uuid.uuid4())
    with conn.transaction():
        conn.execute(
            "INSERT INTO corpus_versions (id, label, status, is_active)"
            " VALUES (%s, %s, 'draft', false)",
            (corpus_version_id, label),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO corpus_version_documents"
                " (corpus_version_id, document_version_id) VALUES (%s, %s)",
                [(corpus_version_id, version_id) for version_id in document_version_ids],
            )
    return corpus_version_id


def publish_corpus_version(conn: psycopg.Connection[Any], corpus_version_id: str) -> None:
    """Atomically make a draft corpus version the single active one.

    Both updates happen in one transaction; readers see either the old or
    the new active pointer, never zero or two. The partial unique index
    ``corpus_versions_single_active`` fails any racing second publisher —
    that race surfaces as :class:`PublishConflictError`, never a raw
    database error.
    """
    try:
        with conn.transaction():
            conn.execute(
                "UPDATE corpus_versions SET is_active = false, status = 'superseded'"
                " WHERE is_active"
            )
            cur = conn.execute(
                "UPDATE corpus_versions SET is_active = true, status = 'active',"
                " published_at = now() WHERE id = %s AND status = 'draft'",
                (corpus_version_id,),
            )
            if cur.rowcount != 1:
                raise ValueError(
                    f"corpus version {corpus_version_id} does not exist or is not a draft"
                )
    except psycopg.errors.UniqueViolation as exc:
        raise PublishConflictError(
            f"corpus version {corpus_version_id} lost the publish race: "
            "another version was activated concurrently; re-read the active "
            "pointer and retry if still applicable"
        ) from exc


def active_corpus_version(conn: psycopg.Connection[Any]) -> str | None:
    """Return the currently active corpus version id, if any."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("SELECT id FROM corpus_versions WHERE is_active").fetchone()
    return None if row is None else str(row["id"])
