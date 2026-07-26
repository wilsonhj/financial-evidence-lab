"""Citation hash / document-version verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fel_workers.ingestion.parser import text_hash


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
                # Compute and compare against any provided hash on the evidence row.
                provided = item.get("text_hash")
                if provided and provided != actual:
                    blockers.append(f"citation_hash_mismatch:{span_id}")
        status = item.get("citation_status")
        if status == "invalid":
            blockers.append(f"citation_marked_invalid:{span_id}")
    del payload
    return blockers


__all__ = ["verify_citations"]
