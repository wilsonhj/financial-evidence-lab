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
