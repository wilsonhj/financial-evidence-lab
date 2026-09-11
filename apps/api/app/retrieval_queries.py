"""Immutable query admission and idempotency storage."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import psycopg
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.auth import TenantContext
from app.config import settings
from app.costs import (
    reserve_query_cost,
)
from app.errors import api_error

# Planner identity persisted on every query/run. Kept in one place so the query
# guard's run<->query planner-pin agreement always holds.
PLANNER_VERSION = "synonym-planner/v1"

# Generation identity persisted on every run (immutable lineage). Only the
# deterministic mock structured provider is wired; any other pin fails closed at
# generation time, so the persisted pin is always load-bearing.
GENERATION_PROVIDER = "mock"
GENERATION_MODEL = "mock-structured-v1"


class CreateQuery(BaseModel):
    """Request body for creating an immutable query (contract CreateQuery)."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    parent_query_id: uuid.UUID | None = None
    as_of: AwareDatetime | None = None
    corpus_version_id: uuid.UUID | None = None
    index_version_id: uuid.UUID | None = None
    lanes: list[str] | None = Field(default=None, max_length=4)
    top_k: int | None = Field(default=None, ge=1, le=100)
    forms: list[str] | None = Field(default=None, max_length=20)
    periods: list[str] | None = Field(default=None, max_length=20)


class EvidenceFeedback(BaseModel):
    """Request body for append-only evidence feedback (contract EvidenceFeedback)."""

    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    label: str
    reason: str | None = Field(default=None, max_length=2000)
    supersedes_feedback_id: uuid.UUID | None = None


_FEEDBACK_LABELS = frozenset({"relevant", "irrelevant", "duplicate", "temporally_invalid"})


def _idempotent_replay(
    conn: psycopg.Connection[Any], ctx: TenantContext, endpoint: str, key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT response_body FROM idempotency_keys"
        " WHERE key = %s AND org_id = %s AND endpoint = %s",
        (key, ctx.org_id, endpoint),
    ).fetchone()
    return dict(row["response_body"]) if row else None


def _idempotent_store(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    endpoint: str,
    key: str,
    status: int,
    body: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO idempotency_keys (key, org_id, endpoint, response_status, response_body)"
        " VALUES (%s, %s, %s, %s, %s)",
        (key, ctx.org_id, endpoint, status, json.dumps(body)),
    )


def _resolve_index(conn: psycopg.Connection[Any], body: CreateQuery) -> dict[str, Any]:
    """Resolve the pinned index version (explicit pin or workspace active default)."""
    if body.index_version_id is not None:
        row = conn.execute(
            "SELECT id, corpus_version_id, config_hash, status, published_at,"
            " embedding_provider, embedding_model"
            " FROM retrieval_index_versions WHERE id = %s",
            (str(body.index_version_id),),
        ).fetchone()
        if (
            row is None
            or row["status"] not in {"ready", "superseded"}
            or row["published_at"] is None
        ):
            raise api_error(
                422, "INDEX_NOT_PUBLISHED", "index_version_id must be a published index."
            )
    else:
        row = conn.execute(
            "SELECT id, corpus_version_id, config_hash, status, published_at,"
            " embedding_provider, embedding_model"
            " FROM retrieval_index_versions WHERE is_active AND status = 'ready'"
        ).fetchone()
        if row is None:
            raise api_error(409, "NO_ACTIVE_INDEX", "No active retrieval index is available.")
    if body.corpus_version_id is not None and str(body.corpus_version_id) != str(
        row["corpus_version_id"]
    ):
        raise api_error(
            422, "CORPUS_INDEX_MISMATCH", "corpus_version_id does not match the pinned index."
        )
    return dict(row)


def _insert_query(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    *,
    workspace_id: str,
    body: CreateQuery,
    index: dict[str, Any],
    plan_dict: dict[str, Any],
    effective_as_of: datetime,
) -> str:
    query_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO queries ("
        " id, org_id, workspace_id, created_by, question, effective_as_of,"
        " corpus_version_id, index_version_id, plan, planner_version, parent_query_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
        (
            query_id,
            ctx.org_id,
            workspace_id,
            ctx.user_id,
            body.question,
            effective_as_of,
            str(index["corpus_version_id"]),
            str(index["id"]),
            json.dumps(plan_dict),
            PLANNER_VERSION,
            str(body.parent_query_id) if body.parent_query_id else None,
        ),
    )
    return query_id


def _insert_run(
    conn: psycopg.Connection[Any],
    ctx: TenantContext,
    *,
    query_id: str,
    index: dict[str, Any],
    mode: str,
    parent_run_id: str | None,
) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO retrieval_runs ("
        " id, org_id, query_id, parent_run_id, mode, config_hash,"
        " embedding_provider, embedding_model, generation_provider, generation_model,"
        " planner_version"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id,
            ctx.org_id,
            query_id,
            parent_run_id,
            mode,
            index["config_hash"],
            index["embedding_provider"],
            index["embedding_model"],
            GENERATION_PROVIDER,
            GENERATION_MODEL,
            PLANNER_VERSION,
        ),
    )
    reserve_query_cost(conn, ctx, run_id, settings().research_query_cost_usd)
    return run_id


def _accepted_body(query_id: str, run_id: str) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "run_id": run_id,
        "events_url": f"/v1/retrieval-runs/{run_id}/events",
    }
