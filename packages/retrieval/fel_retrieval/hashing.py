"""Content hashing and span-slice re-verification."""

from __future__ import annotations

import hashlib


def content_sha256(text: str) -> str:
    """Repository-wide ``sha256:<hex>`` of UTF-8 text."""
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def verify_span_slice(
    canonical_text: str,
    *,
    start_char: int,
    end_char: int,
    expected_content: str,
    expected_hash: str,
) -> str | None:
    """Return a rejection code if the slice fails closed; otherwise None."""
    if start_char < 0 or end_char < start_char or end_char > len(canonical_text):
        return "OFFSET_MISMATCH"
    sliced = canonical_text[start_char:end_char]
    if sliced != expected_content:
        return "HASH_MISMATCH"
    if content_sha256(sliced) != expected_hash:
        return "HASH_MISMATCH"
    if expected_hash != content_sha256(expected_content):
        return "HASH_MISMATCH"
    return None
