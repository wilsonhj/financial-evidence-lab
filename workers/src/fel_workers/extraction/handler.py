"""extraction_run job handler (M3-102)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import psycopg

from fel_providers.interfaces import StructuredLLMProvider
from fel_workers.extraction.hashing import hash_json, sha256_hex
from fel_workers.extraction.persist import (
    MemoryPersistStore,
    PostgresPersistStore,
    assert_workspace_ownership,
)
from fel_workers.extraction.types import (
    WORKFLOW_VERSION,
    EvidenceBlock,
    ExtractionMode,
    ExtractionRunRequest,
    WorkflowState,
)
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

JOB_KIND_EXTRACTION_RUN = "extraction_run"
DEFAULT_EXTRACTION_QUEUE = "extraction"

__all__ = [
    "DEFAULT_EXTRACTION_QUEUE",
    "JOB_KIND_EXTRACTION_RUN",
    "handle_extraction_run",
    "request_from_payload",
]


def handle_extraction_run(
    conn: psycopg.Connection[Any] | None,
    structured_llm: StructuredLLMProvider,
    payload: dict[str, Any],
    *,
    lease_check: Callable[[], bool] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    use_memory_stores: bool | None = None,
    job_org_id: str | None = None,
) -> WorkflowState:
    """Dispatch one ``extraction_run`` job.

    Store selection never depends on payload SHAPE. A live ``conn`` means the
    durable Postgres stores; memory stores are used only when there is no
    connection to write to, or when a caller forces them with an explicit
    ``use_memory_stores=True``. Inline ``evidence``/``spans`` blocks supply the
    text for the run and nothing else — they used to also (silently) redirect
    every write to in-memory stores, so a run with a live connection returned
    ``waiting_review``, the job was marked ``succeeded``, and not one row was
    written. The two spellings are exact synonyms on every path.

    Tenancy on the durable path comes from the JOB, never from the payload:
    ``job_org_id`` (``ClaimedJob.org_id``) must be present AND equal the payload
    ``org_id``. A NULL job org is not "no constraint" — read that way, the
    payload self-asserts its own tenant, and the remaining control does not
    close the gap: ``assert_workspace_ownership`` only checks that workspace and
    org agree with each other, not that the enqueuer was entitled to that org.
    ``jobs.org_id`` is nullable by design for platform jobs (``sec_discovery``
    and friends legitimately have none); ``extraction_run`` writes tenant data
    and is not one of them. The requirement is scoped to the durable path —
    memory stores write nothing, so there is no tenant to protect.
    """
    request = request_from_payload(payload)
    memory = use_memory_stores if use_memory_stores is not None else conn is None
    if job_org_id is not None and request.org_id != job_org_id:
        raise ValueError(
            f"extraction_run payload org_id {request.org_id} does not match "
            f"job org_id {job_org_id}"
        )
    if not memory:
        if conn is None:
            raise RuntimeError("database persistence selected without a connection")
        if job_org_id is None:
            raise ValueError(
                "extraction_run reached the durable path with no job org_id: "
                f"refusing to persist run {request.run_id} on the payload's own "
                f"claim to org {request.org_id}. Enqueue extraction_run jobs "
                "tenant-bound — queue.enqueue(..., org_id=<tenant>)."
            )
        assert_workspace_ownership(conn, org_id=request.org_id, workspace_id=request.workspace_id)
        persist: Any = PostgresPersistStore(conn)
        persist.mark_running(run_id=request.run_id, org_id=request.org_id)
        from fel_workers.extraction.persist import PostgresCheckpointStore, PostgresEventStore

        checkpoint: Any = PostgresCheckpointStore(conn)
        events: Any = PostgresEventStore(conn)
    else:
        persist = MemoryPersistStore()
        from fel_workers.extraction.checkpoint import MemoryCheckpointStore
        from fel_workers.extraction.events import MemoryEventStore

        checkpoint = MemoryCheckpointStore()
        events = MemoryEventStore()

    evidence = _evidence_from_payload(payload)
    state = WorkflowState(request=request, evidence=evidence)
    deps = WorkflowDeps(
        structured_llm=structured_llm,
        checkpoint=checkpoint,
        events=events,
        persist=persist,
        lease_check=lease_check or (lambda: True),
        cancel_check=cancel_check or (lambda: False),
        evidence_loader=(lambda _req: list(evidence)),
    )
    return run_extraction_workflow(state, deps)


def request_from_payload(payload: dict[str, Any]) -> ExtractionRunRequest:
    """Build a pinned run request from a queue payload or inline test dict."""
    data = dict(payload["request"]) if isinstance(payload.get("request"), dict) else dict(payload)

    modes_raw = data.get("modes") or ["kpi"]
    if not isinstance(modes_raw, (list, tuple)):
        raise ValueError("extraction_run modes must be a list")
    allowed = {"kpi", "guidance", "revenue_driver"}
    modes_list: list[ExtractionMode] = []
    for mode in modes_raw:
        mode_s = str(mode)
        if mode_s not in allowed:
            raise ValueError(f"unsupported extraction mode: {mode_s!r}")
        modes_list.append(cast(ExtractionMode, mode_s))
    modes: tuple[ExtractionMode, ...] = tuple(modes_list)
    as_of_raw = data.get("as_of") or datetime.now().isoformat()
    as_of = datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00"))

    run_id = str(data.get("run_id") or data.get("id") or "")
    org_id = str(data.get("org_id") or "")
    workspace_id = str(data.get("workspace_id") or "")
    entity_id = str(data.get("entity_id") or "")
    for label, value in (
        ("run_id", run_id),
        ("org_id", org_id),
        ("workspace_id", workspace_id),
        ("entity_id", entity_id),
    ):
        if not value:
            raise ValueError(f"extraction_run payload missing {label}")
        UUID(value)

    input_manifest = data.get("input_manifest") or {}
    input_hash = str(data.get("input_hash") or hash_json(input_manifest))
    if not input_hash.startswith("sha256:"):
        input_hash = sha256_hex(input_hash)

    return ExtractionRunRequest(
        run_id=run_id,
        org_id=org_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        modes=modes,
        as_of=as_of,
        corpus_version_id=str(data.get("corpus_version_id") or entity_id),
        ontology_version=str(data.get("ontology_version") or "saas-metrics/v1"),
        workflow_version=str(data.get("workflow_version") or WORKFLOW_VERSION),
        provider=str(data.get("provider") or "mock"),
        model=str(data.get("model") or "mock-structured-v1"),
        policy_id=str(data.get("policy_id") or run_id),
        input_manifest=dict(input_manifest),
        input_hash=input_hash,
        max_calls=int(data.get("max_calls") or 10),
        max_input_tokens=int(data.get("max_input_tokens") or 100_000),
        max_output_tokens=int(data.get("max_output_tokens") or 20_000),
        max_cost_usd=Decimal(str(data.get("max_cost_usd") or "2.00")),
        max_wall_seconds=int(data.get("max_wall_seconds") or 600),
        issuer_label=str(data.get("issuer_label") or "Unknown Issuer"),
    )


def _evidence_from_payload(payload: dict[str, Any]) -> list[EvidenceBlock]:
    raw_blocks = payload.get("evidence") or payload.get("spans") or []
    blocks: list[EvidenceBlock] = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        span_id = str(item.get("source_span_id") or item.get("id") or "")
        if not span_id:
            continue
        text = str(item.get("text") or "")
        text_hash = str(item.get("text_hash") or sha256_hex(text))
        document_version_id = str(item.get("document_version_id") or "")
        if not document_version_id:
            raise ValueError(
                f"evidence span {span_id} missing document_version_id "
                "(must not default to source_span_id)"
            )
        published = item.get("published_at")
        published_at = None
        if published:
            published_at = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        blocks.append(
            EvidenceBlock(
                source_span_id=span_id,
                document_version_id=document_version_id,
                text=text,
                text_hash=text_hash,
                published_at=published_at,
            )
        )
    return blocks
