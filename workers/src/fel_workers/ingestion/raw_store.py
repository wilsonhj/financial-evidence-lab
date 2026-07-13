"""Immutable raw source store (T0102, FR-ING-002).

Raw bytes go to the StorageProvider under a content-addressed key
(``raw/sha256/<hex>``), so identical bytes always land on the same key and
the provider's immutability guarantee makes overwrites with different
content impossible. Document metadata rows carry the spec 10.3 temporal
fields and match the contracts DocumentMeta shape.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from fel_providers.interfaces import StorageProvider
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
    """Return (content_hash, storage_key) for raw bytes."""
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
) -> StoredDocument:
    """Store raw bytes immutably and record the document metadata row."""
    content_hash, storage_key = content_address(raw)
    storage.put(storage_key, raw)
    document_id = document_id_for_accession(accession)
    cur = conn.execute(
        """
        INSERT INTO documents
            (id, entity_id, accession, form, source_url, content_hash,
             storage_key, mime_type, published_at, filed_at,
             period_start, period_end)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (accession) DO NOTHING
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
    )
    return StoredDocument(
        document_id=document_id,
        content_hash=content_hash,
        storage_key=storage_key,
        created=bool(cur.rowcount),
    )
