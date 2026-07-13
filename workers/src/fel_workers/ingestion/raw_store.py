"""Immutable raw source store (T0102, FR-ING-002).

Raw bytes go to the StorageProvider under a content-addressed key
(``raw/sha256/<hex>``), so identical bytes always land on the same key and
the provider's immutability guarantee makes overwrites with different
content impossible. Document metadata rows carry the spec 10.3 temporal
fields and match the contracts DocumentMeta shape.

Divergence policy (fail closed): a re-fetch of an already-recorded
accession whose bytes differ raises :class:`DivergentAccessionError`
(reason code ``DIVERGENT_ACCESSION_CONTENT``) instead of silently keeping
the old row while downstream parses the new bytes. The pipeline turns that
into a quarantine entry for operator review. Superseding in place was
rejected: the raw store is immutable evidence, and ``documents.content_hash``
must always match the bytes the published version was parsed from. A
re-fetch with identical bytes remains an idempotent no-op replay.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fel_providers.interfaces import StorageProvider
from fel_workers.ingestion.errors import DivergentAccessionError
from fel_workers.ingestion.parser import ID_NAMESPACE


@dataclass(frozen=True)
class StoredDocument:
    """Result of storing one immutable raw source."""

    document_id: str
    content_hash: str
    storage_key: str
    created: bool
    """False when the accession was already recorded (idempotent replay)."""


def content_address(raw: bytes) -> tuple[str, str]:
    """Return (content_hash, storage_key) for raw bytes.

    The hash uses the repository-wide ``sha256:<hex>`` format (the same
    format every DB CHECK constraint expects); callers hash once here and
    pass the value through.
    """
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest}", f"raw/sha256/{digest}"


def document_id_for_accession(accession: str) -> str:
    """Deterministic document id so replays never mint a second identity."""
    return str(uuid.uuid5(ID_NAMESPACE, f"document|{accession}"))


def store_raw_document(
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
    content_hash: str | None = None,
    storage_key: str | None = None,
) -> StoredDocument:
    """Store raw bytes immutably and record the document metadata row.

    ``content_hash``/``storage_key`` may be passed pre-computed (from
    :func:`content_address`) so the bytes are hashed exactly once.

    Raises :class:`DivergentAccessionError` when the accession is already
    recorded with different bytes (see module docstring).
    """
    if content_hash is None or storage_key is None:
        content_hash, storage_key = content_address(raw)
    storage.put(storage_key, raw)
    document_id = document_id_for_accession(accession)
    with conn.cursor(row_factory=dict_row) as cur:
        inserted = cur.execute(
            """
            INSERT INTO documents
                (id, entity_id, accession, form, source_url, content_hash,
                 storage_key, mime_type, published_at, filed_at,
                 period_start, period_end)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO NOTHING
            RETURNING id
            """,
            (
                document_id,
                entity_id,
                accession,
                form,
                source_url,
                content_hash,
                storage_key,
                mime_type,
                published_at,
                filed_at,
                period_start,
                period_end,
            ),
        ).fetchone()
        if inserted is None:
            existing = cur.execute(
                "SELECT id, content_hash FROM documents WHERE accession = %s",
                (accession,),
            ).fetchone()
            if existing is None:  # pragma: no cover — conflict row must exist
                raise RuntimeError(f"accession {accession!r} conflicted but has no row")
            existing_hash = str(existing["content_hash"])
            if existing_hash != content_hash:
                raise DivergentAccessionError(
                    f"accession {accession!r} was already ingested with "
                    f"content {existing_hash} but the re-fetched bytes hash "
                    f"to {content_hash}; refusing to overwrite immutable "
                    "evidence — investigate the source before re-ingesting",
                    document_id=str(existing["id"]),
                    existing_content_hash=existing_hash,
                    new_content_hash=content_hash,
                )
    return StoredDocument(
        document_id=document_id,
        content_hash=content_hash,
        storage_key=storage_key,
        created=inserted is not None,
    )
