"""Redacted structured telemetry for extraction runs (M3-107)."""

from __future__ import annotations

import logging
from typing import Any

from fel_workers.extraction.events import redact_log_payload

log = logging.getLogger("fel_workers.extraction.telemetry")


def emit(
    event: str,
    *,
    run_id: str,
    step_name: str | None = None,
    **fields: Any,
) -> None:
    """Emit a structured log line with sensitive keys redacted."""
    payload = redact_log_payload(
        {
            "event": event,
            "run_id": run_id,
            "step_name": step_name,
            **fields,
        }
    )
    log.info("extraction_telemetry %s", payload)


__all__ = ["emit"]
