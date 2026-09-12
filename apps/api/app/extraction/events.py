"""Extraction event writes on the already run-locked caller transaction."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fel_workers.extraction.events import redact_event_payload


def append(
    conn: psycopg.Connection[dict[str, Any]],
    org_id: str,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Caller locks the run before child writes; identity is allocated only here."""
    row = conn.execute(
        "INSERT INTO extraction_run_events(org_id,run_id,event_type,payload) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (org_id, run_id, event_type, Jsonb(redact_event_payload(payload, event_type=event_type))),
    ).fetchone()
    assert row is not None
    return int(row["id"])


TERMINAL_EVENTS = frozenset({"run_succeeded", "run_failed", "run_cancelled"})


def project(row: dict[str, Any]) -> dict[str, Any]:
    """Finite metadata fields with checked values; legacy control trees never leave SQL."""
    import re
    from uuid import UUID

    from app.errors import api_error
    from app.extraction import reads
    from fel_workers.extraction.events import ALLOWED_EVENT_TYPES
    from fel_workers.extraction.types import STAGE_ORDER

    if row["event_type"] not in ALLOWED_EVENT_TYPES or not 1 <= row["id"] <= 2**53 - 1:
        raise api_error(
            422,
            "VALIDATION_ERROR",
            "Stored event is not representable.",
            {"resource_id": str(row["run_id"])},
        )
    raw = row["payload"]
    if not isinstance(raw, dict):
        raise api_error(422, "VALIDATION_ERROR", "Stored event metadata is invalid.")
    safe: dict[str, Any] = {}
    for key in (
        "count",
        "conflicts",
        "proposal_count",
        "attempt",
        "calls_used",
        "input_tokens_used",
        "output_tokens_used",
        "input_tokens",
        "output_tokens",
    ):
        value = raw.get(key)
        if type(value) is int and 0 <= value <= 2**53 - 1:
            safe[key] = value
    for key in ("run_id", "review_id", "record_id", "version_id"):
        value = raw.get(key)
        try:
            if isinstance(value, str):
                safe[key] = str(UUID(value))
        except ValueError:
            pass
    for key in ("input_hash", "output_hash"):
        value = raw.get(key)
        if isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            safe[key] = value
    for key in ("cost_usd",):
        value = raw.get(key)
        if isinstance(value, str) and re.fullmatch(r"\d{1,12}(\.\d{1,12})?", value):
            safe[key] = value
    if raw.get("step_name") in STAGE_ORDER:
        safe["step_name"] = raw["step_name"]
    if raw.get("status") in (
        "queued",
        "running",
        "waiting_review",
        "succeeded",
        "failed",
        "cancelled",
    ):
        safe["status"] = raw["status"]
    if type(raw.get("skipped")) is bool:
        safe["skipped"] = raw["skipped"]
    if raw.get("error") is not None:
        safe["error"] = {"code": "EXTRACTION_FAILED", "message": "Extraction step failed."}
    event = {
        "schema_version": "extraction-event/v1",
        "id": row["id"],
        "run_id": str(row["run_id"]),
        "type": row["event_type"],
        "occurred_at": row["occurred_at"].isoformat(),
        "payload": redact_event_payload(safe, event_type=row["event_type"]),
    }
    if len(frame(event).encode()) > 65536:
        raise reads.too_large(str(row["run_id"]))
    return event


def frame(event: dict[str, Any]) -> str:
    from fel_workers.extraction.hashing import canonical_json

    return f"id: {event['id']}\nevent: {event['type']}\ndata: {canonical_json(event)}\n\n"


def fetch(
    ctx: Any, run_id: str, after: int, *, check_resume: bool = False
) -> tuple[list[dict[str, Any]], str]:
    from app.db import tenant_connection
    from app.dependencies import resolve_membership
    from app.errors import api_error
    from app.extraction import reads

    current = resolve_membership(ctx)
    with tenant_connection(current, snapshot_read=True) as conn:
        run = reads.run(conn, run_id, ctx.org_id)
        if (
            check_resume
            and after
            and conn.execute(
                "SELECT 1 FROM extraction_run_events WHERE org_id=%s AND run_id=%s AND id=%s",
                (ctx.org_id, run_id, after),
            ).fetchone()
            is None
        ):
            raise api_error(404, "NOT_FOUND", "Extraction event not found.")
        sizes = conn.execute(
            "SELECT id,octet_length(payload::text) AS size FROM extraction_run_events "
            "WHERE org_id=%s AND run_id=%s AND id>%s ORDER BY id LIMIT 200",
            (ctx.org_id, run_id, after),
        ).fetchall()
        if any(row["size"] > 65536 for row in sizes):
            raise reads.too_large(run_id)
        rows = conn.execute(
            "SELECT id,run_id,event_type,payload,created_at AS occurred_at "
            "FROM extraction_run_events "
            "WHERE org_id=%s AND run_id=%s AND id=ANY(%s::bigint[]) ORDER BY id",
            (ctx.org_id, run_id, [row["id"] for row in sizes]),
        ).fetchall()
        return [project(row) for row in rows], run["status"]


def page(
    conn: psycopg.Connection[dict[str, Any]],
    org: str,
    run_id: str,
    limit: int | None,
    cursor: str | None,
    order: Any,
) -> dict[str, Any]:
    from app.extraction import reads
    from app.pagination import read_page, scope

    run = reads.run(conn, run_id, org)
    rows, metadata = read_page(
        conn,
        query="SELECT id,octet_length(payload::text) AS size FROM extraction_run_events "
        "WHERE org_id=%s AND run_id=%s",
        params=(org, run_id),
        keys=("id",),
        request_scope=scope("extraction_events", org, run_id),
        limit=limit,
        token=cursor,
        order=order,
        force_page=True,
    )
    assert metadata is not None
    if any(row["size"] > 65536 for row in rows):
        raise reads.too_large(run["id"])
    data = conn.execute(
        "SELECT id,run_id,event_type,payload,created_at AS occurred_at "
        "FROM extraction_run_events WHERE org_id=%s AND run_id=%s AND id=ANY(%s::bigint[])",
        (org, run_id, [row["id"] for row in rows]),
    ).fetchall()
    by_id = {row["id"]: row for row in data}
    return {
        "run_id": run_id,
        "items": [project(by_id[row["id"]]) for row in rows],
        **{key: metadata[key] for key in ("limit", "next_cursor", "previous_cursor")},
    }
