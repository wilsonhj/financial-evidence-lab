"""Bounded current approval heads used by the caller's review transaction."""

from typing import Any

import psycopg

from app.errors import api_error
from app.extraction import approved, reads, validation
from fel_ontology import load_saas_metrics


def relevant_rows(
    rows: list[dict[str, Any]], selected_ids: set[str], required_ids: set[str]
) -> list[dict[str, Any]]:
    """Conservative dependency superset for the current deterministic worker rules.

    Duplicates/conflicts require the same metric (ontology keys retain metric
    identity); segment sums also stay within one metric. The only cross-metric
    identities in validate/accounting.py are RPO/cRPO and revenue/COGS/gross
    profit. Keep all contexts within these families rather than guessing at a
    malformed period, currency or dimension. Unknown identity stays included.
    Explicit group members always remain dependencies, even if edited apart.
    """
    metrics = {
        row["payload"].get("metric_id")
        for row in rows
        if str(row["id"]) in selected_ids and isinstance(row["payload"].get("metric_id"), str)
    }
    if len([row for row in rows if str(row["id"]) in selected_ids]) != len(selected_ids):
        validation.invalid(sorted(selected_ids)[0])
    for family in ({"rpo", "crpo"}, {"revenue", "cogs", "gross_profit"}):
        if metrics & family:
            metrics |= family
    result = []
    known_metrics = {metric.id for metric in load_saas_metrics().metrics}
    for row in rows:
        payload = row["payload"]
        metric = payload.get("metric_id")
        if (
            str(row["id"]) in selected_ids | required_ids
            or not isinstance(metric, str)
            or not metric
            or metric != row["metric_id"]
            or payload.get("kind") not in ("kpi", "guidance", "revenue_driver")
            or (payload.get("kind") == "kpi" and metric not in known_metrics)
            or metric in metrics
        ):
            result.append(row)
    return result


def heads(
    conn: psycopg.Connection[dict[str, Any]], org: str, run_ids: list[str]
) -> list[dict[str, Any]]:
    """Read bounded immutable head provenance; callers serialize on source runs."""
    rows = conn.execute(
        "SELECT r.id,v.id AS version_id,v.origin_proposal_id,p.run_id AS origin_run_id,"
        "octet_length(v.validation_context::text) AS size "
        "FROM approved_extraction_records r JOIN approved_extraction_versions v "
        "ON v.id=r.current_version_id AND v.org_id=r.org_id "
        "JOIN extraction_proposals p ON p.id=v.origin_proposal_id AND p.org_id=v.org_id "
        "WHERE r.org_id=%s AND (p.run_id=ANY(%s::uuid[]) OR EXISTS ("
        "SELECT 1 FROM jsonb_array_elements(CASE WHEN "
        "jsonb_typeof(v.validation_context->'source_runs')='array' "
        "THEN v.validation_context->'source_runs' ELSE '[]'::jsonb END) pin "
        "WHERE pin->>'run_id'=ANY(%s::text[]))) ORDER BY r.id LIMIT 201",
        (org, run_ids, run_ids),
    ).fetchall()
    if len(rows) > 200:
        raise reads.too_large(str(rows[200]["id"]))
    for row in rows:
        if row["size"] is None:
            validation.invalid(str(row["id"]))
        if row["size"] > 1048576:
            raise reads.too_large(str(row["id"]))
        context = conn.execute(
            "SELECT validation_context FROM approved_extraction_versions WHERE id=%s AND org_id=%s",
            (row["version_id"], org),
        ).fetchone()
        if context is None:
            validation.invalid(str(row["id"]))
        provenance = context["validation_context"]
        if not isinstance(provenance, dict):
            validation.invalid(str(row["id"]))
        pins = provenance.get("source_runs")
        if (
            not isinstance(pins, list)
            or not 1 <= len(pins) <= 100
            or not all(isinstance(pin, dict) and isinstance(pin.get("run_id"), str) for pin in pins)
            or len({pin["run_id"] for pin in pins}) != len(pins)
        ):
            validation.invalid(str(row["id"]))
        row["source_pins"] = pins
    return rows


def expand_runs(conn: psycopg.Connection[dict[str, Any]], org: str, run_ids: set[str]) -> list[str]:
    """Discover merged-source dependencies before acquiring the first run lock."""
    for _ in range(100):
        current = heads(conn, org, sorted(run_ids))
        expanded = (
            run_ids
            | {pin["run_id"] for row in current for pin in row["source_pins"]}
            | {str(row["origin_run_id"]) for row in current}
        )
        if len(expanded) > 100:
            raise reads.too_large(sorted(run_ids)[0])
        if expanded == run_ids:
            return sorted(run_ids)
        run_ids = expanded
    raise api_error(409, "CONFLICT", "Approved extraction dependencies changed.")


def current_rows(
    conn: psycopg.Connection[dict[str, Any]],
    org: str,
    rows: list[dict[str, Any]],
    runs: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Replace accepted inputs and restore merged survivors using locked current heads.

    Original source IDs remain the validation identity. Current head content is
    never written back into the immutable source proposal or conflict history.
    """
    from app.extraction.review import DiscoveryChanged

    current_heads = heads(conn, org, sorted(runs))
    if any(pin["run_id"] not in runs for head in current_heads for pin in head["source_pins"]):
        raise DiscoveryChanged()
    origins = {str(row["id"]): row for row in rows}
    result = {
        str(row["id"]): dict(row) for row in rows if row["state"] not in ("rejected", "superseded")
    }
    record_origins: dict[str, str] = {}
    seen: set[str] = set()
    for head in current_heads:
        rid, pid = str(head["id"]), str(head["origin_proposal_id"])
        if pid not in origins or pid in seen:
            validation.invalid(rid)
        seen.add(pid)
        conn.execute(
            "SELECT id FROM approved_extraction_records WHERE id=%s AND org_id=%s FOR UPDATE",
            (rid, org),
        )
        current = approved.detail(conn, org, rid)
        if current["version_id"] != str(head["version_id"]):
            raise DiscoveryChanged()
        pinned_runs = {pin["run_id"]: runs[pin["run_id"]] for pin in head["source_pins"]}
        if validation.source_context(pinned_runs)["source_runs"] != head["source_pins"]:
            validation.invalid(rid)
        result[pid] = {
            **origins[pid],
            "payload": current["payload"],
            "evidence": current["evidence"],
            "validation_summary": {},
            "source_run_ids": sorted(pinned_runs),
        }
        record_origins[rid] = pid
    return [result[pid] for pid in sorted(result)], record_origins
