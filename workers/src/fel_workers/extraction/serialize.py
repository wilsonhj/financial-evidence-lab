"""JSON-safe stage output for event-backed crash-resume."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from fel_workers.extraction.types import EvidenceBlock


def serialize_stage_output(output: Any) -> Any:
    """JSON-safe stage output (migration 0004 has no steps.output column)."""
    if output is None:
        return None
    if isinstance(output, EvidenceBlock):
        data = asdict(output)
        published = data.get("published_at")
        if isinstance(published, datetime):
            data["published_at"] = published.isoformat()
        return data
    if is_dataclass(output) and not isinstance(output, type):
        data = asdict(output)
        published = data.get("published_at")
        if isinstance(published, datetime):
            data["published_at"] = published.isoformat()
        return data
    if isinstance(output, list):
        return [serialize_stage_output(item) for item in output]
    if isinstance(output, dict):
        return {str(k): serialize_stage_output(v) for k, v in output.items()}
    if isinstance(output, (str, int, float, bool)):
        return output
    return str(output)


__all__ = ["serialize_stage_output"]
