"""ADR-0024 conflict occurrence identity, derived only from persisted run pins."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg

from fel_workers.extraction.errors import StepFailed
from fel_workers.extraction.types import ConflictDraft


def _occurrence_run(
    conn: psycopg.Connection[Any], *, org_id: str, workspace_id: str, members: list[str]
) -> str | None:
    if len(set(members)) < 2:
        raise ValueError("conflict groups require at least two distinct members")
    rows = conn.execute(
        "SELECT p.id, p.run_id, r.input_manifest FROM extraction_proposals p"
        " JOIN extraction_runs r ON r.id=p.run_id AND r.org_id=p.org_id"
        " AND r.workspace_id=p.workspace_id"
        " WHERE p.id = ANY(%s::uuid[]) AND p.org_id=%s AND p.workspace_id=%s",
        (members, org_id, workspace_id),
    ).fetchall()
    if {str(row[0]) for row in rows} != set(members):
        raise StepFailed("conflict members are missing or outside workspace", code="conflict_scope")
    opted_in: set[str] = set()
    runs = {str(row[1]) for row in rows}
    for _, run_id, manifest in rows:
        if not isinstance(manifest, dict):
            raise StepFailed(
                "malformed conflict occurrence policy manifest", code="conflict_policy"
            )
        if "conflict_occurrence_policy" not in manifest:
            continue
        if manifest["conflict_occurrence_policy"] != "run/v1":
            raise StepFailed("unknown conflict occurrence policy", code="conflict_policy")
        opted_in.add(str(run_id))
    if opted_in and (len(runs) != 1 or opted_in != runs):
        raise StepFailed("conflict occurrence members must share one run", code="conflict_scope")
    return next(iter(opted_in)) if opted_in else None


def persist_conflicts(
    conn: psycopg.Connection[Any], *, org_id: str, workspace_id: str, drafts: list[ConflictDraft]
) -> list[ConflictDraft]:
    """Keep legacy NULL groups and isolate explicitly pinned run/v1 occurrences.

    The facade asserts workspace ownership. Its existing atomic output stage
    owns the transaction; this leaf neither commits nor changes financial keys.
    """
    out: list[ConflictDraft] = []
    for draft in drafts:
        occurrence = _occurrence_run(
            conn, org_id=org_id, workspace_id=workspace_id, members=draft.member_proposal_ids
        )
        conn.execute(
            """
            INSERT INTO extraction_conflicts (
                id, org_id, workspace_id, conflict_key, reason_codes, status, occurrence_run_id
            ) VALUES (%s,%s,%s,%s,%s,'open',%s)
            ON CONFLICT (org_id, workspace_id, conflict_key, occurrence_run_id) DO NOTHING
            """,
            (
                draft.id or str(uuid4()),
                org_id,
                workspace_id,
                draft.conflict_key,
                draft.reason_codes,
                occurrence,
            ),
        )
        row = conn.execute(
            "SELECT id,status FROM extraction_conflicts WHERE org_id=%s AND workspace_id=%s"
            " AND conflict_key=%s AND occurrence_run_id IS NOT DISTINCT FROM %s::uuid",
            (org_id, workspace_id, draft.conflict_key, occurrence),
        ).fetchone()
        if row is None:
            raise StepFailed("conflict row missing after upsert", code="conflict_upsert")
        if str(row[1]) != "open":
            raise StepFailed(
                f"conflict {draft.conflict_key} already exists as {str(row[1])!r}; "
                "refusing unreviewed members in an adjudicated group",
                code="conflict_terminal",
            )
        draft.id = str(row[0])
        for proposal_id in draft.member_proposal_ids:
            conn.execute(
                "INSERT INTO extraction_conflict_members (conflict_id,proposal_id,org_id)"
                " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (draft.id, proposal_id, org_id),
            )
        out.append(draft)
    return out
