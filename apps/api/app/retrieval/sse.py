"""Server-sent-event replay of a run's persisted trace.

Emission is a separate GET, after the create transaction has committed, so a
stream never shows an uncommitted event. ``Last-Event-ID`` resumes from a seq,
and a leading heartbeat comment gives the client immediate liveness.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from app.auth import TenantContext
from app.db import tenant_connection
from app.retrieval.serializers import _event_body

# SSE keep-alive comment. Emitted at stream open (and, for a still-open run,
# between polls) so a client sees liveness within the contract's 15-30s window.
_HEARTBEAT = ": keep-alive\n\n"


def _sse_stream(ctx: TenantContext, run_id: str, last_event_id: int) -> Iterator[str]:
    """Yield persisted events (seq > last_event_id) as text/event-stream.

    Events are already committed when this generator runs (they were written in
    the create transaction), so nothing uncommitted is ever emitted. A leading
    heartbeat comment gives the client immediate liveness.
    """
    yield _HEARTBEAT
    with tenant_connection(ctx, snapshot_read=True) as conn:
        rows = conn.execute(
            "SELECT seq, event_type, payload, created_at FROM retrieval_events"
            " WHERE run_id = %s AND seq > %s ORDER BY seq",
            (run_id, last_event_id),
        ).fetchall()
    for row in rows:
        body = json.dumps(
            _event_body(row, run_id), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        yield f"id: {int(row['seq'])}\nevent: {row['event_type']}\ndata: {body}\n\n"
