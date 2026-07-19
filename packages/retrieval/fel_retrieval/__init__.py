"""Retrieval package: deterministic item IDs and hash-verified chunk builders."""

from fel_retrieval.config import CHUNKER_VERSION, config_hash
from fel_retrieval.hashing import content_sha256, verify_span_slice
from fel_retrieval.ids import ID_NAMESPACE, item_id, source_anchor
from fel_retrieval.item_builder import build_items
from fel_retrieval.models import BuildResult, Rejection, RetrievalItemDraft

__all__ = [
    "CHUNKER_VERSION",
    "ID_NAMESPACE",
    "BuildResult",
    "Rejection",
    "RetrievalItemDraft",
    "build_items",
    "config_hash",
    "content_sha256",
    "item_id",
    "source_anchor",
    "verify_span_slice",
]
