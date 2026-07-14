"""Golden-file regeneration for the T0111 parser stress fixtures.

Regeneration workflow (documented; run from the repository root):

1. Make the intentional parser/normalizer change and bump
   ``PARSER_VERSION`` / ``NORMALIZER_VERSION`` accordingly.
2. Regenerate the stress goldens (this rewrites the ``*_golden.json``
   files listed in ``GOLDEN_FIXTURES`` in place)::

       PYTHONPATH=workers/src:packages/providers \\
           .venv/bin/python workers/tests/fixtures/regen_parser_goldens.py

3. Inspect ``git diff`` on the golden files hunk by hunk: every changed
   offset, hash, id, or value must be explained by the intentional change.
   Golden churn without a version bump is a regression, not a refresh.
4. Re-run the suite: ``.venv/bin/pytest workers/tests/test_parser_golden_stress.py``.

The test suite imports this module (via ``importlib``) and rebuilds the
golden payloads from the committed fixture bytes, so the serialization
here is the single source of truth for both generation and verification.

The goldens pin the FULL parse output — canonical text hash/length,
section hierarchy, spans (ids, offsets, text hashes), tables, contexts,
units, raw inline facts, diagnostics — plus the normalized
financial-fact/v1 records produced by the T0104 normalizer under fixed
synthetic entity/version identifiers.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from fel_workers.ingestion.parser import PARSER_VERSION, ParsedDocument, parse_filing
from fel_workers.ingestion.xbrl import NORMALIZER_VERSION, normalize_facts

FIXTURES_DIR = pathlib.Path(__file__).parent

# Fixed synthetic identifiers so normalized fact ids are deterministic.
GOLDEN_ENTITY_ID = "00000000-0000-4000-8000-0000000000e1"
GOLDEN_VERSION_ID = "00000000-0000-4000-8000-0000000000d1"

# fixture -> golden file. Add new stress fixtures here.
GOLDEN_FIXTURES: dict[str, str] = {
    "synthetic_10q_stress.html": "synthetic_10q_stress_golden.json",
    "synthetic_8k_narrative.html": "synthetic_8k_narrative_golden.json",
}

_NOTE = (
    "Golden expectations for the SYNTHETIC stress fixture {fixture}; "
    "regenerate ONLY on an intentional parser/normalizer version bump via "
    "workers/tests/fixtures/regen_parser_goldens.py (workflow in that "
    "module's docstring)."
)


def _serialize_sections(parsed: ParsedDocument) -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "parent_id": s.parent_id,
            "heading": s.heading,
            "heading_path": list(s.heading_path),
            "order": s.order,
            "start_char": s.start_char,
            "end_char": s.end_char,
        }
        for s in parsed.sections
    ]


def _serialize_spans(parsed: ParsedDocument) -> list[dict[str, Any]]:
    return [
        {
            "id": sp.id,
            "section_id": sp.section_id,
            "start_char": sp.start_char,
            "end_char": sp.end_char,
            "text_hash": sp.text_hash,
        }
        for sp in parsed.spans
    ]


def _serialize_tables(parsed: ParsedDocument) -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "section_id": t.section_id,
            "order": t.order,
            "caption": t.caption,
            "headers": list(t.headers),
            "rows": [list(row) for row in t.rows],
        }
        for t in parsed.tables
    ]


def _serialize_contexts(parsed: ParsedDocument) -> dict[str, Any]:
    return {
        context_id: {
            "instant": context.instant.isoformat() if context.instant else None,
            "start": context.start.isoformat() if context.start else None,
            "end": context.end.isoformat() if context.end else None,
            "dimensions": dict(context.dimensions),
        }
        for context_id, context in sorted(parsed.contexts.items())
    }


def _serialize_raw_facts(parsed: ParsedDocument) -> list[dict[str, Any]]:
    return [
        {
            "concept": f.concept,
            "context_ref": f.context_ref,
            "unit_ref": f.unit_ref,
            "scale": f.scale,
            "decimals": f.decimals,
            "sign": f.sign,
            "format": f.format,
            "raw_text": f.raw_text,
            "span_id": f.span_id,
            "section_id": f.section_id,
            "start_char": f.start_char,
            "end_char": f.end_char,
        }
        for f in parsed.facts
    ]


def _serialize_normalized_facts(parsed: ParsedDocument) -> list[dict[str, Any]]:
    normalized = normalize_facts(
        parsed, entity_id=GOLDEN_ENTITY_ID, document_version_id=GOLDEN_VERSION_ID
    )
    return [
        {
            "id": fact.id,
            "concept": fact.concept,
            "value": fact.value,
            "unit": fact.unit,
            "scale": fact.scale,
            "period_type": fact.period_type,
            "period_instant": (fact.period_instant.isoformat() if fact.period_instant else None),
            "period_start": fact.period_start.isoformat() if fact.period_start else None,
            "period_end": fact.period_end.isoformat() if fact.period_end else None,
            "dimensions": dict(fact.dimensions),
            "source_span_id": fact.source_span_id,
            "reported_or_derived": fact.reported_or_derived,
            "confidence": fact.confidence,
            "fact_key": fact.fact_key,
            "duplicate_of": fact.duplicate_of,
            "restates": fact.restates,
        }
        for fact in normalized
    ]


def build_golden(fixture_name: str) -> dict[str, Any]:
    """Build the full golden payload for one committed fixture."""
    raw = (FIXTURES_DIR / fixture_name).read_bytes()
    parsed = parse_filing(raw)
    return {
        "_note": _NOTE.format(fixture=fixture_name),
        "parser_version": PARSER_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "golden_entity_id": GOLDEN_ENTITY_ID,
        "golden_version_id": GOLDEN_VERSION_ID,
        "content_hash": parsed.content_hash,
        "text_length": len(parsed.text),
        "text_hash": "sha256:" + hashlib.sha256(parsed.text.encode()).hexdigest(),
        "sections": _serialize_sections(parsed),
        "spans": _serialize_spans(parsed),
        "tables": _serialize_tables(parsed),
        "contexts": _serialize_contexts(parsed),
        "units": dict(sorted(parsed.units.items())),
        "facts": _serialize_raw_facts(parsed),
        "normalized_facts": _serialize_normalized_facts(parsed),
        "diagnostics": list(parsed.diagnostics),
    }


def main() -> None:
    for fixture_name, golden_name in GOLDEN_FIXTURES.items():
        golden = build_golden(fixture_name)
        path = FIXTURES_DIR / golden_name
        path.write_text(json.dumps(golden, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {path}")  # noqa: T201 — operator-facing script


if __name__ == "__main__":
    main()
