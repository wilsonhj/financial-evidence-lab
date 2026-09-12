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
