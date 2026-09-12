"""Atomic extraction run creation and existing durable queue envelope."""

import os
from decimal import Decimal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.auth import TenantContext
from app.corpus import require_corpus
from app.db import tenant_connection
from app.errors import api_error
from app.extraction import events, evidence, reads, receipts, serializers
from app.extraction.models import RunCreate
from app.observability import record_audit_event
from app.pagination import utc_cutoff
from fel_ontology import load_saas_metrics
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
            raise api_error(
                503, "EXTRACTION_NOT_CONFIGURED", "Extraction provider is not configured."
            )
        if str(body.entity_id) != str(ws["entity_id"]):
            raise api_error(422, "VALIDATION_ERROR", "Entity does not match the workspace.")
        policy = conn.execute(
            "SELECT * FROM extraction_policies WHERE org_id=%s ORDER BY version DESC LIMIT 1",
            (ctx.org_id,),
        ).fetchone()
        if policy is None:
            raise api_error(
                503, "EXTRACTION_NOT_CONFIGURED", "Extraction policy is not configured."
            )
        corpus_id = body.corpus_version_id
        if corpus_id is None:
            corpus = conn.execute(
                "SELECT id FROM corpus_versions WHERE is_active AND status='active'"
            ).fetchone()
            if corpus is None:
                raise api_error(
                    503, "EXTRACTION_NOT_CONFIGURED", "Current corpus is not configured."
                )
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
            "max_wall_seconds,created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                "create:" + key,
                limits["max_calls"],
                limits["max_input_tokens"],
                limits["max_output_tokens"],
                limits["max_cost_usd"],
                limits["max_wall_seconds"],
                ctx.user_id,
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
