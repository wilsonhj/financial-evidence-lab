"""Fixed read-only tool allowlists for extraction roles (M3-WF-009)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fel_workers.extraction.errors import IntegrityError

ToolFn = Callable[..., Any]

ALLOWED_TOOLS = frozenset(
    {
        "lookup_pinned_evidence",
        "lookup_ontology_metric",
        "lookup_xbrl_facts",
        "normalize_preview",
        "validate_preview",
    }
)

ROLE_TOOL_ALLOWLISTS: dict[str, frozenset[str]] = {
    "classifier": frozenset({"lookup_pinned_evidence", "lookup_ontology_metric"}),
    "fact_candidates": frozenset(
        {"lookup_pinned_evidence", "lookup_ontology_metric", "lookup_xbrl_facts"}
    ),
    "kpi": frozenset(
        {
            "lookup_pinned_evidence",
            "lookup_ontology_metric",
            "lookup_xbrl_facts",
            "normalize_preview",
            "validate_preview",
        }
    ),
    "guidance": frozenset(
        {
            "lookup_pinned_evidence",
            "lookup_ontology_metric",
            "normalize_preview",
            "validate_preview",
        }
    ),
    "driver_mapper": frozenset(
        {
            "lookup_pinned_evidence",
            "lookup_ontology_metric",
            "normalize_preview",
            "validate_preview",
        }
    ),
}


def _require_uuid(value: str, *, field: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


@dataclass
class ToolContext:
    """Pinned evidence/ontology/xbrl lookups available to allowlisted tools."""

    evidence_by_span: Mapping[str, dict[str, Any]]
    ontology_by_metric: Mapping[str, dict[str, Any]]
    xbrl_by_document_version: Mapping[str, list[dict[str, Any]]]

    def lookup_pinned_evidence(self, *, source_span_id: str) -> dict[str, Any]:
        span_id = _require_uuid(source_span_id, field="source_span_id")
        block = self.evidence_by_span.get(span_id)
        if block is None:
            raise IntegrityError(f"span not in pinned evidence bundle: {span_id}")
        # Never return raw text to callers that log — tools return metadata + hash.
        return {
            "source_span_id": span_id,
            "document_version_id": block["document_version_id"],
            "text_hash": block["text_hash"],
            "char_len": len(block.get("text", "")),
        }

    def lookup_ontology_metric(self, *, metric_id: str) -> dict[str, Any]:
        if not metric_id or not isinstance(metric_id, str):
            raise ValueError("metric_id required")
        metric = self.ontology_by_metric.get(metric_id)
        if metric is None:
            raise ValueError(f"unknown metric_id: {metric_id}")
        return dict(metric)

    def lookup_xbrl_facts(self, *, document_version_id: str) -> list[dict[str, Any]]:
        doc_id = _require_uuid(document_version_id, field="document_version_id")
        return list(self.xbrl_by_document_version.get(doc_id, []))

    def normalize_preview(self, *, raw_value: str, unit: str | None = None) -> dict[str, Any]:
        from fel_workers.extraction.normalize.numeric import preview_normalize

        return preview_normalize(raw_value, unit=unit)

    def validate_preview(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        from fel_workers.extraction.validate.schema import validate_payload_item

        errors = validate_payload_item(payload)
        return {"ok": not errors, "errors": errors}


def invoke_tool(
    *,
    role: str,
    tool_name: str,
    ctx: ToolContext,
    kwargs: dict[str, Any],
) -> Any:
    allow = ROLE_TOOL_ALLOWLISTS.get(role)
    if allow is None:
        raise ValueError(f"unknown role: {role}")
    if tool_name not in ALLOWED_TOOLS or tool_name not in allow:
        raise PermissionError(f"tool {tool_name!r} not allowlisted for role {role}")
    fn = getattr(ctx, tool_name)
    return fn(**kwargs)


__all__ = [
    "ALLOWED_TOOLS",
    "ROLE_TOOL_ALLOWLISTS",
    "ToolContext",
    "invoke_tool",
]
