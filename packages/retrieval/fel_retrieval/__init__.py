"""Retrieval package: deterministic item IDs, hash-verified chunk builders,
and versioned index build/publish with an exact-vs-HNSW recall oracle."""

from fel_retrieval.config import CHUNKER_VERSION, config_hash
from fel_retrieval.embeddings import embed_drafts, format_halfvec
from fel_retrieval.hashing import content_sha256, verify_span_slice
from fel_retrieval.ids import ID_NAMESPACE, item_id, source_anchor
from fel_retrieval.index_build import (
    BuildOutcome,
    DBConnection,
    IndexBuildError,
    build_and_publish,
    build_index,
    hnsw_search,
    publish_index_version,
)
from fel_retrieval.index_version import (
    DIMENSIONS,
    DISTANCE,
    IndexVersionSpec,
    index_version_id,
    make_index_version_spec,
)
from fel_retrieval.item_builder import build_items, effective_chunker_config
from fel_retrieval.lanes import (
    LANE_DENSE,
    LANE_FACTS,
    LANE_LEXICAL,
    LANE_TABLES,
    LaneCandidate,
    LaneQuery,
    dense_lane,
    facts_lane,
    lexical_lane,
    tables_lane,
)
from fel_retrieval.models import BuildResult, Rejection, RetrievalItemDraft
from fel_retrieval.oracle import cosine_distance, exact_knn, recall_at_k
from fel_retrieval.planner import (
    PlanBudgets,
    PlanFilters,
    PlannerValidationError,
    QueryPlan,
    QueryRequest,
    classify_intent,
    derive_budgets,
    expand_variants,
    plan_query,
)  # noqa: E501

__all__ = [
    "CHUNKER_VERSION",
    "DIMENSIONS",
    "DISTANCE",
    "ID_NAMESPACE",
    "LANE_DENSE",
    "LANE_FACTS",
    "LANE_LEXICAL",
    "LANE_TABLES",
    "BuildOutcome",
    "BuildResult",
    "DBConnection",
    "IndexBuildError",
    "IndexVersionSpec",
    "LaneCandidate",
    "LaneQuery",
    "PlanBudgets",
    "PlanFilters",
    "PlannerValidationError",
    "QueryPlan",
    "QueryRequest",
    "Rejection",
    "RetrievalItemDraft",
    "build_and_publish",
    "build_index",
    "build_items",
    "classify_intent",
    "config_hash",
    "content_sha256",
    "cosine_distance",
    "dense_lane",
    "derive_budgets",
    "effective_chunker_config",
    "embed_drafts",
    "exact_knn",
    "expand_variants",
    "facts_lane",
    "format_halfvec",
    "hnsw_search",
    "index_version_id",
    "item_id",
    "lexical_lane",
    "make_index_version_spec",
    "plan_query",
    "publish_index_version",
    "recall_at_k",
    "source_anchor",
    "tables_lane",
    "verify_span_slice",
]
