"""Evidence assembly with cutoff / corpus / span-hash revalidation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fel_workers.extraction.errors import CutoffViolation, IntegrityError
from fel_workers.extraction.types import EvidenceBlock, ExtractionRunRequest
from fel_workers.ingestion.parser import text_hash


def assemble_evidence(
    request: ExtractionRunRequest,
    *,
    spans: list[Mapping[str, Any]],
) -> list[EvidenceBlock]:
    """Build the pinned evidence bundle; fail closed on cutoff/hash mismatch."""
    manifest_ids = set(request.input_manifest.get("source_span_ids") or [])
    blocks: list[EvidenceBlock] = []
    for span in spans:
        span_id = str(span["id"])
        if manifest_ids and span_id not in manifest_ids:
            continue
        published_at = span.get("published_at")
        if isinstance(published_at, datetime) and published_at > request.as_of:
            raise CutoffViolation(
                f"span {span_id} published_at {published_at.isoformat()} after as_of"
            )
        text = str(span.get("text") or "")
        expected = span.get("text_hash")
        actual = text_hash(text)
        if expected and expected != actual:
            raise IntegrityError(f"span hash mismatch for {span_id}")
        doc_version = str(span.get("document_version_id") or "")
        if not doc_version:
            raise IntegrityError(f"span {span_id} missing document_version_id")
        blocks.append(
            EvidenceBlock(
                source_span_id=span_id,
                document_version_id=doc_version,
                text=text,
                text_hash=actual,
                published_at=published_at if isinstance(published_at, datetime) else None,
            )
        )
    if not blocks:
        raise IntegrityError("no cutoff-visible evidence spans in pinned manifest")
    return blocks


__all__ = ["assemble_evidence"]
