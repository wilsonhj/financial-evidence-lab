"""One transaction for reviewed proposal states, immutable approvals and receipts."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.auth import TenantContext
from app.db import tenant_connection
from app.errors import api_error
from app.extraction import conflicts, events, reads, receipts, runs, validation
from app.extraction.models import ReviewCommand
from app.observability import record_audit_event


class DiscoveryChanged(Exception):
    """A writer expanded an earlier lock class: restart without holding late locks."""


def _discover(
    conn: psycopg.Connection[dict[str, Any]], ids: list[str], org: str
) -> tuple[list[str], list[str]]:
    selected = conn.execute(
        "SELECT id,run_id,workspace_id FROM extraction_proposals "
        "WHERE org_id=%s AND id=ANY(%s::uuid[]) ORDER BY id",
        (org, ids),
    ).fetchall()
    if {str(row["id"]) for row in selected} != set(ids):
        raise api_error(404, "NOT_FOUND", "Extraction proposal not found.")
    if len({row["workspace_id"] for row in selected}) != 1:
        raise api_error(409, "CONFLICT", "Review inputs must share a workspace.")
    run_ids = {str(row["run_id"]) for row in selected}
    groups = conn.execute(
        "SELECT DISTINCT m.conflict_id FROM extraction_conflict_members m "
        "WHERE m.org_id=%s AND m.proposal_id=ANY(%s::uuid[]) ORDER BY m.conflict_id LIMIT 101",
        (org, ids),
    ).fetchall()
    if len(groups) > 100:
        raise reads.too_large(ids[0])
    group_ids = [str(row["conflict_id"]) for row in groups]
    for group_id in group_ids:
        members = conflicts.detail(conn, group_id, org)["member_versions"]
        member_runs = conn.execute(
            "SELECT DISTINCT run_id FROM extraction_proposals "
            "WHERE org_id=%s AND id=ANY(%s::uuid[])",
            (org, list(members)),
        ).fetchall()
        run_ids.update(str(row["run_id"]) for row in member_runs)
    if len(run_ids) > 100:
        raise reads.too_large(ids[0])
    return sorted(run_ids), group_ids


def _locked_rows(
    conn: psycopg.Connection[dict[str, Any]], org: str, run_ids: list[str]
) -> list[dict[str, Any]]:
    sizes = conn.execute(
        "SELECT id,octet_length(payload::text)+octet_length(validation_summary::text) AS size "
        "FROM extraction_proposals WHERE org_id=%s AND run_id=ANY(%s::uuid[]) "
        "ORDER BY id LIMIT 201 FOR UPDATE",
        (org, run_ids),
    ).fetchall()
    if len(sizes) > 200:
        raise reads.too_large(str(sizes[200]["id"]))
    rows = []
    for size in sizes:
        if size["size"] > 1048576:
            raise reads.too_large(str(size["id"]))
        row = conn.execute(
            "SELECT id,run_id,workspace_id,kind,metric_id,state,version,payload,"
            "validation_summary FROM extraction_proposals WHERE id=%s AND org_id=%s",
            (size["id"], org),
        ).fetchone()
        assert row is not None
        edges = conn.execute(
            "SELECT source_span_id,document_version_id,role "
            "FROM extraction_proposal_evidence WHERE proposal_id=%s AND org_id=%s "
            "ORDER BY source_span_id,document_version_id,role LIMIT 201",
            (row["id"], org),
        ).fetchall()
        if len(edges) > 200:
            raise reads.too_large(str(row["id"]))
        row["evidence"] = [{k: str(v) for k, v in edge.items()} for edge in edges]
        rows.append(row)
    return rows


def apply(
    ctx: TenantContext, command: ReviewCommand, key: str, request_id: str
) -> receipts.Receipt:
    if ctx.role not in ("owner", "editor", "reviewer"):
        raise api_error(403, "FORBIDDEN", "Role may not review extractions.")
    body = command.model_dump(mode="json", exclude_unset=True)
    body["extraction_ids"] = sorted(body["extraction_ids"])
    if "conflict_resolution" in body:
        body["conflict_resolution"] = sorted(
            body["conflict_resolution"], key=lambda item: item["conflict_id"]
        )
        for decision in body["conflict_resolution"]:
            decision["selected_winner_ids"] = sorted(decision["selected_winner_ids"])
    if command.action == "edit":
        body["patch"] = sorted(body["patch"], key=lambda item: item["extraction_id"])
    request = {"actor": ctx.user_id, "action": command.action, "body": body}
    for attempt in range(3):
        try:
            with tenant_connection(ctx) as conn:
                replay = receipts.begin(
                    conn, ctx.org_id, "extraction.review." + command.action, key, request
                )
                if replay:
                    return replay
                return _apply(conn, ctx, body, key, request_id, request)
        except (
            DiscoveryChanged,
            psycopg.errors.SerializationFailure,
            psycopg.errors.DeadlockDetected,
        ):
            if attempt == 2:
                raise api_error(
                    409, "CONFLICT", "Concurrent extraction changes; retry the request."
                ) from None
    raise AssertionError("Unreachable retry boundary")


def _apply(
    conn: psycopg.Connection[dict[str, Any]],
    ctx: TenantContext,
    body: dict[str, Any],
    key: str,
    request_id: str,
    request: dict[str, Any],
) -> receipts.Receipt:
    ids = body["extraction_ids"]
    run_ids, group_ids = _discover(conn, ids, ctx.org_id)
    locked_runs = {run_id: runs.locked_run(conn, UUID(run_id), ctx.org_id) for run_id in run_ids}
    if _discover(conn, ids, ctx.org_id) != (run_ids, group_ids):
        raise DiscoveryChanged()
    for group_id in group_ids:
        conn.execute(
            "SELECT id FROM extraction_conflicts WHERE id=%s AND org_id=%s FOR UPDATE",
            (group_id, ctx.org_id),
        )
    if _discover(conn, ids, ctx.org_id) != (run_ids, group_ids):
        raise DiscoveryChanged()
    rows = _locked_rows(conn, ctx.org_id, run_ids)
    selected = {str(row["id"]): row for row in rows if str(row["id"]) in ids}
    if set(body["expected_versions"]) != set(ids) or any(
        body["expected_versions"][pid] != selected[pid]["version"] for pid in ids
    ):
        raise api_error(412, "PRECONDITION_FAILED", "Selected proposals changed.")
    if any(row["state"] not in ("proposed", "needs_review") for row in selected.values()):
        raise api_error(409, "CONFLICT", "Selected proposal is terminal.")
    if any(
        locked_runs[str(row["run_id"])]["status"] != "waiting_review" for row in selected.values()
    ):
        raise api_error(409, "CONFLICT", "Extraction is not awaiting review.")
    groups = {gid: conflicts.detail(conn, gid, ctx.org_id) for gid in group_ids}
    decisions = conflicts.decisions_for(groups, body, {str(row["id"]): row for row in rows})
    approvals = []
    workspace_id = str(next(iter(selected.values()))["workspace_id"])
    if body["action"] != "reject":
        validation_rows = [
            dict(row) for row in rows if row["state"] not in ("rejected", "superseded")
        ]
        if body["action"] == "edit":
            patches = {patch["extraction_id"]: patch for patch in body["patch"]}
            if len(patches) != len(body["patch"]) or set(patches) != set(ids):
                raise api_error(
                    412, "PRECONDITION_FAILED", "Complete selected replacements required."
                )
            for row in validation_rows:
                if str(row["id"]) in patches:
                    replacement = patches[str(row["id"])]
                    row.update(
                        payload=replacement["payload"],
                        evidence=replacement["evidence"],
                        validation_summary={},
                    )
        result = validation.evaluate(conn, validation_rows, locked_runs)
        waived = conflicts.check_evaluated(result, set(ids), groups, decisions, body["action"])
        for pid in ids:
            blockers = result.drafts[pid].validation_summary["blockers"]
            if any(blocker != "duplicate_candidate" or pid not in waived for blocker in blockers):
                validation.invalid(pid)
        from app.extraction import approved

        if body["action"] == "merge":
            from fel_workers.extraction.validate.duplicates import comparability_key_for

            source_id = body["patch"]["payload_source_id"]
            if source_id not in ids:
                raise api_error(
                    412, "PRECONDITION_FAILED", "Merge payload source must be selected."
                )
            source = result.drafts[source_id]
            identity = (
                comparability_key_for(source.payload),
                source.payload.get("definition"),
                source.comparability_key,
            )
            if any(
                (
                    comparability_key_for(result.drafts[pid].payload),
                    result.drafts[pid].payload.get("definition"),
                    result.drafts[pid].comparability_key,
                )
                != identity
                for pid in ids
            ):
                raise api_error(409, "CONFLICT", "Merge inputs are not comparable.")
            merged = deepcopy(source)
            edges = {
                (edge["source_span_id"], edge["document_version_id"], edge["role"]): edge
                for pid in ids
                for edge in result.drafts[pid].evidence
            }
            if len(edges) > 200:
                raise reads.too_large(source_id)
            merged.evidence = [edges[key] for key in sorted(edges)]
            source_runs = {
                str(selected[pid]["run_id"]): locked_runs[str(selected[pid]["run_id"])]
                for pid in ids
            }
            approvals.append(
                approved.create(
                    conn,
                    ctx,
                    workspace_id,
                    merged,
                    validation.source_context(source_runs),
                    body["reason"],
                )
            )
        else:
            for pid in ids:
                run = locked_runs[str(selected[pid]["run_id"])]
                approvals.append(
                    approved.create(
                        conn,
                        ctx,
                        workspace_id,
                        result.drafts[pid],
                        validation.source_context({str(run["id"]): run}),
                        body["reason"],
                    )
                )
    state = {"accept": "accepted", "edit": "accepted", "reject": "rejected", "merge": "superseded"}[
        body["action"]
    ]
    for pid in ids:
        conn.execute(
            "UPDATE extraction_proposals SET state=%s,version=version+1 WHERE id=%s AND org_id=%s",
            (state, pid, ctx.org_id),
        )
    review_id = str(uuid4())
    resolutions = {}
    resolved_groups = []
    for gid, decision in sorted(decisions.items()):
        resolved_at = datetime.now(UTC)
        resolution = {
            "review_id": review_id,
            "selected_winner_ids": decision["selected_winner_ids"],
            "approved_record_ids": [item["record_id"] for item in approvals],
            "reason": decision["reason"],
            "actor_user_id": ctx.user_id,
            "resolved_at": resolved_at.isoformat(),
        }
        conn.execute(
            "UPDATE extraction_conflicts SET status='resolved',resolved_by=%s,"
            "resolved_at=%s,resolution_note=%s WHERE id=%s AND org_id=%s",
            (ctx.user_id, resolved_at, decision["reason"], gid, ctx.org_id),
        )
        projected = conflicts.detail(conn, gid, ctx.org_id)
        projected.pop("etag")
        projected["resolution"] = resolution
        from app.extraction.serializers import etag

        resolved_groups.append({"conflict_id": gid, "etag": etag(projected)})
        resolutions[gid] = resolution
    result_body = {
        "review_id": review_id,
        "action": body["action"],
        "proposal_states": {pid: state for pid in ids},
        "proposal_versions": {pid: selected[pid]["version"] + 1 for pid in ids},
        "approved_record_ids": [item["record_id"] for item in approvals],
        "approved_versions": approvals,
        "resolved_conflicts": resolved_groups,
    }
    conn.execute(
        "INSERT INTO extraction_reviews(id,org_id,workspace_id,action,actor_user_id,reason,"
        "request_id,idempotency_key,expected_versions,input_ids,patch,result_ids) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid[],%s,%s::uuid[])",
        (
            review_id,
            ctx.org_id,
            workspace_id,
            body["action"],
            ctx.user_id,
            body["reason"],
            request_id,
            key,
            Jsonb(body["expected_versions"]),
            ids,
            Jsonb({"command": body, "result": result_body, "resolutions": resolutions}),
            result_body["approved_record_ids"],
        ),
    )
    for run_id in sorted({str(row["run_id"]) for row in selected.values()}):
        finish_review(conn, ctx.org_id, run_id, review_id)
    record_audit_event(conn, ctx, request_id, "extraction.reviewed", "extraction_review", review_id)
    return receipts.save(
        conn, ctx.org_id, "extraction.review." + body["action"], key, request, 200, result_body, {}
    )


def finish_review(
    conn: psycopg.Connection[dict[str, Any]], org: str, run_id: str, review_id: str
) -> None:
    events.append(conn, org, run_id, "review_completed", {"review_id": review_id})
    remaining = conn.execute(
        "SELECT 1 FROM extraction_proposals WHERE org_id=%s AND run_id=%s "
        "AND state IN ('proposed','needs_review') LIMIT 1",
        (org, run_id),
    ).fetchone()
    opened = conn.execute(
        "SELECT 1 FROM extraction_conflicts c JOIN extraction_conflict_members m "
        "ON m.conflict_id=c.id AND m.org_id=c.org_id JOIN extraction_proposals p "
        "ON p.id=m.proposal_id AND p.org_id=m.org_id WHERE c.org_id=%s AND p.run_id=%s "
        "AND c.status='open' LIMIT 1",
        (org, run_id),
    ).fetchone()
    if remaining is None and opened is None:
        events.append(conn, org, run_id, "run_succeeded", {"status": "succeeded"})
        conn.execute(
            "UPDATE extraction_runs SET status='succeeded',finished_at=now() "
            "WHERE id=%s AND org_id=%s AND status='waiting_review'",
            (run_id, org),
        )
