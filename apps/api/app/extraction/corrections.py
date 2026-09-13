"""Immutable approved-version corrections with frozen provenance and exact receipts."""

from datetime import datetime
from uuid import UUID

import psycopg

from app.auth import TenantContext
from app.db import tenant_connection
from app.errors import api_error
from app.extraction import (
    approved,
    conflicts,
    receipts,
    review,
    runs,
    serializers,
    validation,
    validation_peers,
)
from app.extraction.models import CorrectionCommand
from app.observability import record_audit_event


def apply(
    ctx: TenantContext,
    record_id: UUID,
    body: CorrectionCommand,
    key: str,
    expected_etag: str,
    request_id: str,
) -> receipts.Receipt:
    for attempt in range(3):
        try:
            return _apply(ctx, record_id, body, key, expected_etag, request_id)
        except (
            review.DiscoveryChanged,
            psycopg.errors.SerializationFailure,
            psycopg.errors.DeadlockDetected,
        ):
            if attempt == 2:
                raise api_error(
                    409, "CONFLICT", "Concurrent extraction changes; retry the request."
                ) from None
    raise AssertionError("Unreachable retry boundary")


def _apply(
    ctx: TenantContext,
    record_id: UUID,
    body: CorrectionCommand,
    key: str,
    expected_etag: str,
    request_id: str,
) -> receipts.Receipt:
    if ctx.role not in ("owner", "editor", "reviewer"):
        raise api_error(403, "FORBIDDEN", "Role may not correct extractions.")
    command = body.model_dump(mode="json", exclude_unset=True)
    request = {
        "actor": ctx.user_id,
        "resource": str(record_id),
        "action": "correct",
        "if_match": expected_etag,
        "body": command,
    }
    with tenant_connection(ctx) as conn:
        replay = receipts.begin(conn, ctx.org_id, "extraction.correct", key, request)
        if replay:
            return replay
        old = approved.detail(conn, ctx.org_id, str(record_id))
        context = old["validation_context"]
        if not isinstance(context, dict) or not isinstance(context.get("source_runs"), list):
            validation.invalid(str(record_id))
        source_pins = {pin["run_id"]: pin for pin in context["source_runs"]}
        if not 1 <= len(source_pins) <= 100 or len(source_pins) != len(context["source_runs"]):
            validation.invalid(str(record_id))
        origin = conn.execute(
            "SELECT origin_proposal_id FROM approved_extraction_versions "
            "WHERE id=%s AND org_id=%s",
            (old["version_id"], ctx.org_id),
        ).fetchone()
        if origin is None or origin["origin_proposal_id"] is None:
            validation.invalid(str(record_id))
        origin_id = str(origin["origin_proposal_id"])
        peer_run_ids, group_ids = review._discover(conn, [origin_id], ctx.org_id)
        all_runs = sorted(set(peer_run_ids) | set(source_pins))
        locked = {rid: runs.locked_run(conn, UUID(rid), ctx.org_id) for rid in all_runs}
        if review._discover(conn, [origin_id], ctx.org_id) != (peer_run_ids, group_ids):
            raise review.DiscoveryChanged()
        for rid, pin in source_pins.items():
            run = locked[rid]
            if (
                any(
                    str(pin.get(field)) != str(run[field])
                    for field in (
                        "corpus_version_id",
                        "ontology_version",
                        "workflow_version",
                        "policy_id",
                    )
                )
                or datetime.fromisoformat(pin["as_of"].replace("Z", "+00:00")) != run["as_of"]
            ):
                validation.invalid(str(record_id))
        for gid in group_ids:
            conn.execute(
                "SELECT id FROM extraction_conflicts WHERE id=%s AND org_id=%s FOR UPDATE",
                (gid, ctx.org_id),
            )
        peers = review._locked_rows(conn, ctx.org_id, all_runs)
        validation_rows, _ = validation_peers.current_rows(conn, ctx.org_id, peers, locked)
        current = approved.detail(conn, ctx.org_id, str(record_id))
        if serializers.etag(current) != expected_etag:
            raise api_error(412, "PRECONDITION_FAILED", "Approved extraction changed.")
        source = next(row for row in peers if str(row["id"]) == origin_id)
        replacement = {
            **source,
            "payload": command["payload"],
            "evidence": command["evidence"],
            "validation_summary": {},
            "source_run_ids": sorted(source_pins),
        }
        validation_rows = [row for row in validation_rows if str(row["id"]) != origin_id]
        validation_rows.append(replacement)
        validation_rows = validation_peers.relevant_rows(
            validation_rows,
            {origin_id},
            {
                pid
                for gid in group_ids
                for pid in conflicts.detail(conn, gid, ctx.org_id)["member_versions"]
            },
        )
        evaluated = validation.evaluate(conn, validation_rows, locked)
        draft = evaluated.drafts[origin_id]
        if draft.validation_summary["blockers"]:
            validation.invalid(str(record_id))
        if any(origin_id in group.member_proposal_ids for group in evaluated.conflicts):
            raise api_error(409, "CONFLICT", "Correction conflicts with another extraction.")
        if draft.kind != old["kind"] or draft.metric_id != old["metric_id"]:
            raise api_error(
                409, "CONFLICT", "Correction must preserve the logical record identity."
            )
        updated = approved.append_version(
            conn,
            ctx,
            str(record_id),
            draft,
            validation.source_context({rid: locked[rid] for rid in source_pins}),
            command["reason"],
            current["version"] + 1,
            current["version_id"],
        )
        record_audit_event(
            conn,
            ctx,
            request_id,
            "extraction.corrected",
            "approved_extraction_version",
            updated["version_id"],
        )
        return receipts.save(
            conn,
            ctx.org_id,
            "extraction.correct",
            key,
            request,
            201,
            updated,
            {
                "ETag": serializers.etag(updated),
                "Location": f"/v1/approved-extractions/{record_id}/versions/"
                + updated["version_id"],
            },
        )
