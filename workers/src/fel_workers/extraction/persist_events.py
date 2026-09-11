"""Extraction events persistence definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fel_workers.extraction.events import (
    ExtractionEvent,
    MemoryEventStore,
    redact_event_payload,
)


def _lock_event_run(conn: psycopg.Connection[Any], *, org_id: str, run_id: str) -> None:
    """Order same-run commits before child locks or event identity allocation.

    Call inside the event-containing transaction, before its first child write.
    Acquiring this only in append would upgrade existing child FOR SHARE locks
    and let concurrent checkpoint/proposal transactions deadlock. The original
    child trigger still enforces the same-organization parent and terminal guard.
    """
    conn.execute(
        "SELECT id FROM extraction_runs WHERE id = %s AND org_id = %s FOR NO KEY UPDATE",
        (run_id, org_id),
    )


@dataclass
class PostgresEventStore:
    conn: psycopg.Connection[Any]
    _memory: MemoryEventStore = field(default_factory=MemoryEventStore)

    def append(
        self, *, org_id: str, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> ExtractionEvent:
        event = self._memory.append(
            org_id=org_id, run_id=run_id, event_type=event_type, payload=payload
        )
        # Under autocommit the lock and INSERT must share a transaction. Nested
        # appends retain the lock until the caller's outer transaction finishes.
        with self.conn.transaction():
            _lock_event_run(self.conn, org_id=org_id, run_id=run_id)
            self.conn.execute(
                """
                INSERT INTO extraction_run_events (org_id, run_id, event_type, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    org_id,
                    run_id,
                    event_type,
                    json.dumps(redact_event_payload(payload, event_type=event_type)),
                ),
            )
        return event
