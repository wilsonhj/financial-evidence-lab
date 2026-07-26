"""Citation hash / span-pin verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fel_workers.extraction.hashing import sha256_hex
from fel_workers.ingestion.parser import text_hash


def citation_errors(
    payload: dict[str, Any],
    *,
    evidence_by_span: dict[str, dict[str, Any]],
    expected_hashes: dict[str, str] | None = None,
) -> list[str]:
    """Verify cited span ids exist and optional text hashes match (live path)."""
    errors: list[str] = []
    evidence = payload.get("evidence") or payload.get("source_span_ids") or []
    span_ids: list[str] = []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, str):
                span_ids.append(item)
            elif isinstance(item, dict) and item.get("source_span_id"):
                span_ids.append(str(item["source_span_id"]))
    for span_id in span_ids:
        block = evidence_by_span.get(span_id)
        if block is None:
            errors.append(f"cited span not in pinned evidence: {span_id}")
            continue
        if expected_hashes and span_id in expected_hashes:
            actual = block.get("text_hash") or sha256_hex(block.get("text", ""))
            if actual != expected_hashes[span_id]:
                errors.append(f"span hash mismatch: {span_id}")
    return errors


def verify_citations(
    *,
    payload: dict[str, Any],
    evidence: list[dict[str, Any]],
    pinned_spans: Mapping[str, dict[str, Any]],
) -> list[str]:
    """Re-hash pinned span text; mismatches are integrity blockers."""
    blockers: list[str] = []
    if not evidence:
        blockers.append("citation_missing")
        return blockers
    for item in evidence:
        span_id = str(item.get("source_span_id") or "")
        pinned = pinned_spans.get(span_id)
        if pinned is None:
            blockers.append(f"citation_span_not_pinned:{span_id}")
            continue
        expected_doc = item.get("document_version_id")
        if expected_doc and expected_doc != pinned.get("document_version_id"):
            blockers.append(f"citation_document_version_mismatch:{span_id}")
        expected_hash = pinned.get("text_hash")
        text = pinned.get("text")
        if isinstance(text, str):
            actual = text_hash(text)
            if expected_hash and actual != expected_hash:
                blockers.append(f"citation_hash_mismatch:{span_id}")
            elif not expected_hash:
                provided = item.get("text_hash")
                if provided and provided != actual:
                    blockers.append(f"citation_hash_mismatch:{span_id}")
        status = item.get("citation_status")
        if status == "invalid":
            blockers.append(f"citation_marked_invalid:{span_id}")
    del payload
    return blockers


__all__ = ["citation_errors", "verify_citations"]
