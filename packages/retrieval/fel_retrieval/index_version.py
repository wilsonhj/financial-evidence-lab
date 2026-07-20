"""Deterministic retrieval index-version identity (M2-011 / T0202).

Mirrors the ``retrieval_index_versions`` contract in
``db/migrations/0003_retrieval_core.sql``: the primary key is the UUIDv5 of
``(corpus_version_id, config_hash, provider, model, dimensions, distance)`` and
must equal the row's unique tuple, so an identical pinned build reuses/resumes
the same row and any changed pin mints a new id.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fel_retrieval.config import CHUNKER_VERSION, config_hash
from fel_retrieval.ids import ID_NAMESPACE
from fel_retrieval.item_builder import effective_chunker_config

DIMENSIONS = 512
DISTANCE = "cosine"


def index_version_id(
    *,
    corpus_version_id: str,
    config_hash: str,
    provider: str,
    model: str,
    dimensions: int = DIMENSIONS,
    distance: str = DISTANCE,
) -> str:
    """UUIDv5 of the pinned index-version tuple (0003 table comment)."""
    key = "|".join(
        [
            "index_version",
            corpus_version_id,
            config_hash,
            provider,
            model,
            str(dimensions),
            distance,
        ]
    )
    return str(uuid.uuid5(ID_NAMESPACE, key))


@dataclass(frozen=True)
class IndexVersionSpec:
    """Fully-pinned identity + build inputs for one retrieval index version."""

    id: str
    corpus_version_id: str
    chunker_version: str
    chunker_config: dict[str, Any]
    config_hash: str
    embedding_provider: str
    embedding_model: str
    dimensions: int = DIMENSIONS
    distance: str = DISTANCE
    metadata: dict[str, Any] = field(default_factory=dict)


def make_index_version_spec(
    *,
    corpus_version_id: str,
    embedding_provider: str,
    embedding_model: str,
    chunker_config: Mapping[str, Any] | None = None,
    dimensions: int = DIMENSIONS,
    distance: str = DISTANCE,
) -> IndexVersionSpec:
    """Resolve a spec, deriving ``config_hash`` and ``id`` deterministically.

    The config hash is computed from the same effective chunker config the item
    builder uses, so the id, the stored ``chunker_config`` and the items agree.
    """
    if dimensions != DIMENSIONS:
        raise ValueError(f"dimensions must be {DIMENSIONS} (0003 CHECK)")
    if distance != DISTANCE:
        raise ValueError(f"distance must be {DISTANCE!r} (0003 CHECK)")
    effective = effective_chunker_config(chunker_config)
    cfg_hash = config_hash(effective)
    return IndexVersionSpec(
        id=index_version_id(
            corpus_version_id=corpus_version_id,
            config_hash=cfg_hash,
            provider=embedding_provider,
            model=embedding_model,
            dimensions=dimensions,
            distance=distance,
        ),
        corpus_version_id=corpus_version_id,
        chunker_version=CHUNKER_VERSION,
        chunker_config=effective,
        config_hash=cfg_hash,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        dimensions=dimensions,
        distance=distance,
    )
