"""Complete bounded conflict membership, on the caller's tenant transaction."""

from typing import Any
from uuid import UUID

import psycopg

from app.errors import api_error
from app.extraction import reads, serializers
from app.pagination import Order, read_page, scope


def detail(
    conn: psycopg.Connection[dict[str, Any]], conflict_id: UUID | str, org_id: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id,conflict_key,occurrence_run_id,status,reason_codes FROM extraction_conflicts "
        "WHERE id=%s AND org_id=%s",
        (conflict_id, org_id),
    ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "Extraction conflict not found.")
    members = conn.execute(
        "SELECT m.proposal_id,p.version FROM extraction_conflict_members m "
        "JOIN extraction_proposals p ON p.id=m.proposal_id AND p.org_id=m.org_id "
        "WHERE m.conflict_id=%s AND m.org_id=%s ORDER BY m.proposal_id LIMIT 201",
        (conflict_id, org_id),
    ).fetchall()
    if len(members) > 200:
        raise reads.too_large(conflict_id)
    if len(members) < 2:
        raise api_error(
            409, "CONFLICT", "Conflict membership is incomplete.", {"resource_id": str(conflict_id)}
        )
    if len(row["reason_codes"]) > 20:
        raise reads.too_large(conflict_id)
    resolutions = conn.execute(
        "SELECT id,octet_length((patch->'resolutions'->%s)::text) AS size "
        "FROM extraction_reviews WHERE org_id=%s AND patch->'resolutions' ? %s LIMIT 2",
        (str(conflict_id), org_id, str(conflict_id)),
    ).fetchall()
    if len(resolutions) > 1:
        raise api_error(409, "CONFLICT", "Conflict resolution history is ambiguous.")
    resolution = None
    if resolutions:
        if resolutions[0]["size"] > 65536:
            raise reads.too_large(conflict_id)
        saved = conn.execute(
            "SELECT patch->'resolutions'->%s AS resolution FROM extraction_reviews "
            "WHERE id=%s AND org_id=%s",
            (str(conflict_id), resolutions[0]["id"], org_id),
        ).fetchone()
        assert saved is not None
        resolution = saved["resolution"]
    body = {
        "id": str(row["id"]),
        "conflict_key": row["conflict_key"],
        "occurrence_run_id": str(row["occurrence_run_id"]) if row["occurrence_run_id"] else None,
        "status": row["status"],
        "reason_codes": row["reason_codes"],
        "member_versions": {str(member["proposal_id"]): member["version"] for member in members},
        "resolution": resolution,
    }
    body["etag"] = serializers.etag(body)
    return body


def page(
    conn: psycopg.Connection[dict[str, Any]],
    workspace_id: UUID,
    org_id: str,
    status: str | None,
    limit: int | None,
    cursor: str | None,
    order: Order | None,
) -> dict[str, Any]:
    ws = reads.workspace(conn, workspace_id, org_id)
    rows, metadata = read_page(
        conn,
        query="SELECT id,created_at FROM extraction_conflicts WHERE workspace_id=%s "
        "AND org_id=%s AND (%s::text IS NULL OR status=%s)",
        params=(workspace_id, org_id, status, status),
        keys=("created_at", "id"),
        request_scope=scope(
            "extraction_conflicts", org_id, workspace_id, ws["as_of"], extraction_filter=status
        ),
        limit=limit,
        token=cursor,
        order=order,
        force_page=True,
    )
    assert metadata is not None
    return serializers.page([detail(conn, row["id"], org_id) for row in rows], metadata)


def decisions_for(
    groups: dict[str, dict[str, Any]], body: dict[str, Any], rows: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    decisions = body.get("conflict_resolution") or []
    mapped = {decision["conflict_id"]: decision for decision in decisions}
    opened = {gid for gid, group in groups.items() if group["status"] == "open"}
    if len(mapped) != len(decisions) or set(mapped) != opened:
        raise api_error(
            412, "PRECONDITION_FAILED", "Complete open conflict decisions are required."
        )
    selected = set(body["extraction_ids"])
    for gid, decision in mapped.items():
        group = groups[gid]
        if (
            decision["member_versions"] != group["member_versions"]
            or decision["expected_etag"] != group["etag"]
        ):
            raise api_error(412, "PRECONDITION_FAILED", "Conflict membership changed.")
        members = set(group["member_versions"])
        winners = set(decision["selected_winner_ids"])
        if not winners <= selected & members:
            raise api_error(409, "CONFLICT", "Conflict winner must be a selected group member.")
        if body["action"] in ("accept", "edit") and winners != selected & members:
            raise api_error(
                409, "CONFLICT", "Every accepted group input must be an explicit winner."
            )
        if not winners:
            final_terminal = all(
                rows[pid]["state"] in ("rejected", "superseded")
                or (pid in selected and body["action"] in ("reject", "merge"))
                for pid in members
            )
            if not final_terminal:
                raise api_error(
                    409, "CONFLICT", "An empty winner set requires all members disposed."
                )
    return mapped


def check_evaluated(
    result: Any,
    selected: set[str],
    groups: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    action: str,
) -> set[str]:
    """Only an explicit adjudication can discharge a set-level duplicate conflict."""
    from fel_workers.extraction.validate.duplicates import value_fingerprint

    waived_duplicates: set[str] = set()
    for detected in result.conflicts:
        members = set(detected.member_proposal_ids)
        touched = members & selected
        if not touched:
            continue
        covered = [group for group in groups.values() if members <= set(group["member_versions"])]
        if not covered:
            raise api_error(409, "CONFLICT", "Comparable proposals require adjudication.")
        for group in covered:
            if group["status"] == "open":
                winners = set(decisions[group["id"]]["selected_winner_ids"])
                competing = members & winners
                if len(competing) > 1 and action != "merge":
                    raise api_error(
                        409, "CONFLICT", "Conflicting winners cannot be approved together."
                    )
                if touched <= winners or action == "merge":
                    waived_duplicates.update(touched)
            else:
                resolution = group["resolution"]
                if resolution is None:
                    raise api_error(409, "CONFLICT", "Historical conflict lacks winner provenance.")
                winners = members & set(resolution["selected_winner_ids"])
                if (
                    not winners
                    or action != "edit"
                    or any(
                        value_fingerprint(result.drafts[pid].payload)
                        != value_fingerprint(result.drafts[winner].payload)
                        for pid in touched
                        for winner in winners
                    )
                ):
                    raise api_error(409, "CONFLICT", "Proposal contradicts the recorded winner.")
                waived_duplicates.update(touched)
    return waived_duplicates
