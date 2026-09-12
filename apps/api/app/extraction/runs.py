"""Atomic extraction run creation and existing durable queue envelope."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.auth import TenantContext
from app.corpus import require_corpus
from app.db import tenant_connection
from app.errors import api_error
from app.extraction import events, evidence, reads, receipts, serializers
from app.extraction.models import RunCreate
from app.observability import record_audit_event
from app.pagination import utc_cutoff
from fel_ontology import load_saas_metrics
from fel_workers.extraction.handler import request_from_payload
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.types import WORKFLOW_VERSION


def create(
    ctx: TenantContext, workspace_id: UUID, body: RunCreate, key: str, request_id: str
) -> receipts.Receipt:
    if ctx.role not in ("owner", "editor"):
        raise api_error(403, "FORBIDDEN", "Role may not create extraction runs.")
    command = body.model_dump(mode="json", exclude_unset=True)
    for field in ("modes", "source_span_ids", "claim_ids"):
        if field in command:
            command[field] = sorted(command[field])
    request = {
        "actor": ctx.user_id,
        "resource": str(workspace_id),
        "action": "create",
        "body": command,
    }
    with tenant_connection(ctx) as conn:
        reads.workspace(conn, workspace_id, ctx.org_id)
        replay = receipts.begin(conn, ctx.org_id, "extraction.create", key, request)
        if replay:
            return replay
        result = _enqueue(conn, ctx, workspace_id, body, "create:" + key, request_id)
        run_id = result["id"]
        return receipts.save(
            conn,
            ctx.org_id,
            "extraction.create",
            key,
            request,
            202,
            result,
            {"ETag": serializers.etag(result), "Location": f"/v1/extraction-runs/{run_id}"},
        )


def _enqueue(
    conn: psycopg.Connection[dict[str, Any]],
    ctx: TenantContext,
    workspace_id: UUID,
    body: RunCreate,
    key: str,
    request_id: str,
    parent_run_id: UUID | None = None,
) -> dict[str, Any]:
    ws = conn.execute(
        "SELECT * FROM workspaces WHERE id=%s AND org_id=%s FOR SHARE",
        (workspace_id, ctx.org_id),
    ).fetchone()
    if ws is None:
        raise api_error(404, "NOT_FOUND", "Workspace not found.")
    if os.environ.get("FEL_ALLOW_MOCK_LLM", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise api_error(503, "EXTRACTION_NOT_CONFIGURED", "Extraction provider is not configured.")
    if str(body.entity_id) != str(ws["entity_id"]):
        raise api_error(422, "VALIDATION_ERROR", "Entity does not match the workspace.")
    policy = conn.execute(
        "SELECT * FROM extraction_policies WHERE org_id=%s ORDER BY version DESC LIMIT 1",
        (ctx.org_id,),
    ).fetchone()
    if policy is None:
        raise api_error(503, "EXTRACTION_NOT_CONFIGURED", "Extraction policy is not configured.")
    corpus_id = body.corpus_version_id
    if corpus_id is None:
        corpus = conn.execute(
            "SELECT id FROM corpus_versions WHERE is_active AND status='active'"
        ).fetchone()
        if corpus is None:
            raise api_error(503, "EXTRACTION_NOT_CONFIGURED", "Current corpus is not configured.")
        corpus_id = corpus["id"]
    require_corpus(conn, corpus_id)
    limits = {
        field: policy[field]
        for field in (
            "max_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_usd",
            "max_wall_seconds",
        )
    }
    if body.limits is not None:
        for field, value in body.limits.model_dump(exclude_unset=True).items():
            value = Decimal(value) if field == "max_cost_usd" else value
            if value <= 0 or value > limits[field]:
                raise api_error(
                    422, "VALIDATION_ERROR", "Requested limits exceed the selected policy."
                )
            limits[field] = value
    limits["max_cost_usd"] = str(limits["max_cost_usd"])
    cutoff = min(utc_cutoff(body.as_of), ws["as_of"])
    claims = sorted(str(ident) for ident in body.claim_ids or [])
    span_ids = sorted(
        set(str(ident) for ident in body.source_span_ids)
        | set(evidence.selected_claim_spans(conn, ctx.org_id, str(workspace_id), claims))
    )
    blocks = evidence.verify_spans(conn, span_ids, str(body.entity_id), str(corpus_id), cutoff)
    manifest = {
        "source_span_ids": span_ids,
        "claim_ids": claims,
        "corpus_version_id": str(corpus_id),
        "as_of": cutoff.isoformat(),
        "evidence": [{k: v for k, v in block.items() if k != "text"} for block in blocks],
        "conflict_occurrence_policy": "run/v1",
    }
    run_id = str(uuid4())
    pins = {
        "run_id": run_id,
        "org_id": ctx.org_id,
        "workspace_id": str(workspace_id),
        "entity_id": str(body.entity_id),
        "modes": sorted(body.modes),
        "as_of": cutoff.isoformat(),
        "corpus_version_id": str(corpus_id),
        "ontology_version": load_saas_metrics().schema_version,
        "workflow_version": WORKFLOW_VERSION,
        "provider": "mock",
        "model": "mock-structured-v1",
        "policy_id": str(policy["id"]),
        "input_manifest": manifest,
        "input_hash": hash_json(manifest),
        **limits,
    }
    conn.execute(
        "INSERT INTO extraction_runs(id,org_id,workspace_id,entity_id,modes,as_of,"
        "corpus_version_id,"
        "ontology_version,workflow_version,provider,model,policy_id,input_manifest,input_hash,"
        "idempotency_key,max_calls,max_input_tokens,max_output_tokens,max_cost_usd,"
        "max_wall_seconds,created_by,parent_run_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            run_id,
            ctx.org_id,
            workspace_id,
            body.entity_id,
            pins["modes"],
            cutoff,
            corpus_id,
            pins["ontology_version"],
            WORKFLOW_VERSION,
            "mock",
            "mock-structured-v1",
            policy["id"],
            Jsonb(manifest),
            pins["input_hash"],
            key,
            limits["max_calls"],
            limits["max_input_tokens"],
            limits["max_output_tokens"],
            limits["max_cost_usd"],
            limits["max_wall_seconds"],
            ctx.user_id,
            parent_run_id,
        ),
    )
    conn.execute(
        "INSERT INTO jobs(id,org_id,kind,queue,idempotency_key,payload) "
        "VALUES (%s,%s,'extraction_run','extraction',%s,%s)",
        (run_id, ctx.org_id, run_id, Jsonb({"request": pins, "evidence": blocks})),
    )
    events.append(conn, ctx.org_id, run_id, "run_queued", {"modes": pins["modes"]})
    record_audit_event(
        conn,
        ctx,
        request_id,
        "extraction.created",
        "extraction_run",
        run_id,
        {"source_count": len(span_ids)},
    )
    result = reads.run(conn, run_id, ctx.org_id)
    return result


def locked_run(
    conn: psycopg.Connection[dict[str, Any]], run_id: UUID | str, org_id: str
) -> dict[str, Any]:
    found = conn.execute(
        "SELECT id FROM extraction_runs WHERE id=%s AND org_id=%s FOR UPDATE", (run_id, org_id)
    ).fetchone()
    if found is None:
        raise api_error(404, "NOT_FOUND", "Extraction run not found.")
    size = conn.execute(
        "SELECT octet_length(input_manifest::text) AS size FROM extraction_runs "
        "WHERE id=%s AND org_id=%s",
        (run_id, org_id),
    ).fetchone()
    assert size is not None
    if size["size"] > 1048576:
        raise reads.too_large(run_id)
    row = conn.execute(
        f"SELECT {reads.RUN_COLUMNS},org_id,policy_id,input_manifest,input_hash "
        "FROM extraction_runs WHERE id=%s AND org_id=%s",
        (run_id, org_id),
    ).fetchone()
    assert row is not None
    return row


_JOB_REQUEST = (
    "CASE WHEN jsonb_typeof(payload->'request')='object' THEN payload->'request' "
    "ELSE payload-'evidence'-'spans' END"
)


def _bound_job(conn: psycopg.Connection[dict[str, Any]], run: dict[str, Any]) -> str:
    rows = conn.execute(
        f"SELECT id,octet_length(({_JOB_REQUEST})::text) AS size FROM jobs "
        f"WHERE org_id=%s AND kind='extraction_run' AND COALESCE(({_JOB_REQUEST})->>'run_id',"
        f"({_JOB_REQUEST})->>'id')=%s ORDER BY id LIMIT 2 FOR NO KEY UPDATE",
        (run["org_id"], str(run["id"])),
    ).fetchall()
    if len(rows) != 1:
        raise api_error(409, "CONFLICT", "Run has no unambiguous bound job.")
    if rows[0]["size"] > 1048576:
        raise reads.too_large(run["id"])
    row = conn.execute(
        f"SELECT {_JOB_REQUEST} AS request FROM jobs WHERE id=%s AND org_id=%s",
        (rows[0]["id"], run["org_id"]),
    ).fetchone()
    assert row is not None
    try:
        request = request_from_payload({"request": row["request"]})
        matches = (
            request.run_id == str(run["id"])
            and request.org_id == str(run["org_id"])
            and request.as_of == run["as_of"]
            and sorted(request.modes) == sorted(run["modes"])
            and request.input_manifest == run["input_manifest"]
            and request.max_cost_usd == run["max_cost_usd"]
        )
        for field in (
            "workspace_id",
            "entity_id",
            "corpus_version_id",
            "ontology_version",
            "workflow_version",
            "provider",
            "model",
            "policy_id",
            "input_hash",
            "max_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_wall_seconds",
        ):
            matches = matches and str(getattr(request, field)) == str(run[field])
    except (ValueError, TypeError, KeyError, AttributeError):
        matches = False
    if not matches:
        raise api_error(409, "CONFLICT", "Job pins do not match the immutable run.")
    return str(rows[0]["id"])


def cancel(
    ctx: TenantContext, run_id: UUID, key: str, expected_etag: str, request_id: str
) -> receipts.Receipt:
    if ctx.role not in ("owner", "editor"):
        raise api_error(403, "FORBIDDEN", "Role may not cancel extraction runs.")
    request = {
        "actor": ctx.user_id,
        "resource": str(run_id),
        "action": "cancel",
        "if_match": expected_etag,
    }
    with tenant_connection(ctx) as conn:
        reads.run(conn, run_id, ctx.org_id)
        replay = receipts.begin(conn, ctx.org_id, "extraction.cancel", key, request)
        if replay:
            return replay
        row = locked_run(conn, run_id, ctx.org_id)
        current = reads.run(conn, run_id, ctx.org_id)
        if expected_etag != serializers.etag(current):
            raise api_error(412, "PRECONDITION_FAILED", "Extraction run changed.")
        if row["status"] in ("succeeded", "failed", "cancelled"):
            raise api_error(409, "CONFLICT", "Extraction run is terminal.")
        marker = row["cancel_requested_at"] or datetime.now(UTC)
        if row["status"] in ("queued", "running"):
            job_id = _bound_job(conn, row)
            conn.execute(
                "UPDATE jobs SET cancel_requested_at=%s WHERE id=%s AND org_id=%s",
                (marker, job_id, ctx.org_id),
            )
            conn.execute(
                "UPDATE extraction_runs SET cancel_requested_at=%s WHERE id=%s AND org_id=%s",
                (marker, run_id, ctx.org_id),
            )
        else:
            events.append(conn, ctx.org_id, str(run_id), "run_cancelled", {"status": "cancelled"})
            conn.execute(
                "UPDATE extraction_runs SET cancel_requested_at=%s,status='cancelled',"
                "finished_at=%s "
                "WHERE id=%s AND org_id=%s",
                (marker, marker, run_id, ctx.org_id),
            )
        record_audit_event(
            conn, ctx, request_id, "extraction.cancel_requested", "extraction_run", str(run_id)
        )
        result = reads.run(conn, run_id, ctx.org_id)
        return receipts.save(
            conn,
            ctx.org_id,
            "extraction.cancel",
            key,
            request,
            200,
            result,
            {"ETag": serializers.etag(result)},
        )


def rerun(
    ctx: TenantContext, run_id: UUID, reason: str, key: str, request_id: str
) -> receipts.Receipt:
    if ctx.role not in ("owner", "editor"):
        raise api_error(403, "FORBIDDEN", "Role may not rerun extraction.")
    request = {"actor": ctx.user_id, "resource": str(run_id), "action": "rerun", "reason": reason}
    with tenant_connection(ctx) as conn:
        reads.run(conn, run_id, ctx.org_id)
        replay = receipts.begin(conn, ctx.org_id, "extraction.rerun", key, request)
        if replay:
            return replay
        parent = locked_run(conn, run_id, ctx.org_id)
        manifest = parent["input_manifest"]
        if (
            not isinstance(manifest, dict)
            or hash_json(manifest) != parent["input_hash"]
            or parent["ontology_version"] != load_saas_metrics().schema_version
        ):
            raise api_error(
                422, "VALIDATION_ERROR", "Historical source context cannot be revalidated."
            )
        try:
            body = RunCreate.model_validate(
                {
                    "entity_id": parent["entity_id"],
                    "as_of": parent["as_of"],
                    "modes": parent["modes"],
                    "corpus_version_id": parent["corpus_version_id"],
                    "source_span_ids": manifest.get("source_span_ids"),
                    "claim_ids": manifest.get("claim_ids", []),
                }
            )
        except ValidationError:
            raise api_error(
                422, "VALIDATION_ERROR", "Historical source context is incomplete."
            ) from None
        result = _enqueue(
            conn, ctx, parent["workspace_id"], body, "rerun:" + key, request_id, run_id
        )
        record_audit_event(
            conn,
            ctx,
            request_id,
            "extraction.rerun_requested",
            "extraction_run",
            result["id"],
            {"parent_run_id": str(run_id), "reason": reason},
        )
        return receipts.save(
            conn,
            ctx.org_id,
            "extraction.rerun",
            key,
            request,
            202,
            result,
            {"ETag": serializers.etag(result), "Location": f"/v1/extraction-runs/{result['id']}"},
        )
