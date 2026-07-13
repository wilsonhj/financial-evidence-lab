"""T0103: golden-file parser test over the committed SYNTHETIC 10-Q fixture.

The fixture is fabricated (no real company's content); the golden file pins
the full parse output — hierarchy, offsets, span hashes, tables, raw facts —
so any behavioral drift in the parser fails loudly.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest

from fel_workers.ingestion.parser import ParseError, parse_filing

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


TEXT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture(scope="module")
def golden() -> dict[str, object]:
    payload = json.loads(fixture_bytes("synthetic_10q_golden.json"))
    assert isinstance(payload, dict)
    return payload


@pytest.fixture(scope="module")
def parsed():
    return parse_filing(fixture_bytes("synthetic_10q.html"))


def test_matches_golden_sections(parsed, golden) -> None:
    actual = [
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
    assert actual == golden["sections"]


def test_matches_golden_spans(parsed, golden) -> None:
    actual = [
        {
            "id": sp.id,
            "section_id": sp.section_id,
            "start_char": sp.start_char,
            "end_char": sp.end_char,
            "text_hash": sp.text_hash,
        }
        for sp in parsed.spans
    ]
    assert actual == golden["spans"]


def test_matches_golden_tables_and_facts(parsed, golden) -> None:
    tables = [
        {
            "id": t.id,
            "section_id": t.section_id,
            "order": t.order,
            "caption": t.caption,
            "headers": list(t.headers),
            "rows": [list(r) for r in t.rows],
        }
        for t in parsed.tables
    ]
    assert tables == golden["tables"]
    facts = [
        {
            "concept": f.concept,
            "context_ref": f.context_ref,
            "unit_ref": f.unit_ref,
            "scale": f.scale,
            "decimals": f.decimals,
            "sign": f.sign,
            "raw_text": f.raw_text,
            "span_id": f.span_id,
            "section_id": f.section_id,
            "start_char": f.start_char,
            "end_char": f.end_char,
        }
        for f in parsed.facts
    ]
    assert facts == golden["facts"]
    assert parsed.content_hash == golden["content_hash"]
    assert parsed.parser_version == golden["parser_version"]
    assert len(parsed.text) == golden["text_length"]


def test_spans_are_stable_and_verifiable(parsed) -> None:
    """Span invariants of contract source-span/v1: schema-valid hash format,
    offsets that address the canonical text, and hash-of-slice integrity."""
    section_ids = {s.id for s in parsed.sections}
    for span in parsed.spans:
        assert UUID_PATTERN.match(span.id)
        assert span.section_id in section_ids
        assert 0 <= span.start_char < span.end_char <= len(parsed.text)
        assert TEXT_HASH_PATTERN.match(span.text_hash)
        slice_text = parsed.text[span.start_char : span.end_char]
        expected = "sha256:" + hashlib.sha256(slice_text.encode()).hexdigest()
        assert span.text_hash == expected


def test_parse_is_deterministic() -> None:
    raw = fixture_bytes("synthetic_10q.html")
    assert parse_filing(raw) == parse_filing(raw)


def test_section_hierarchy_shape(parsed) -> None:
    orders = [s.order for s in parsed.sections]
    assert orders == sorted(orders)
    by_id = {s.id: s for s in parsed.sections}
    for section in parsed.sections:
        if section.parent_id is not None:
            parent = by_id[section.parent_id]
            assert section.heading_path[:-1] == parent.heading_path
            assert section.heading_path[-1] == section.heading


def test_id_seed_scopes_identifiers() -> None:
    raw = fixture_bytes("synthetic_10q.html")
    default = parse_filing(raw)
    seeded = parse_filing(raw, id_seed="version-a")
    assert {s.id for s in default.sections}.isdisjoint({s.id for s in seeded.sections})
    # Same seed -> same ids (stability across reruns).
    assert parse_filing(raw, id_seed="version-a") == seeded


def test_non_utf8_source_quarantines_with_actionable_diagnostic() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_filing(b"\xff\xfe\x00garbage\x9c")
    assert excinfo.value.reason_code == "ENCODING_ERROR"
    assert "re-fetch" in excinfo.value.diagnostic


def test_undefined_context_is_a_parse_error() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_filing(fixture_bytes("corrupt_missing_context.html"))
    assert excinfo.value.reason_code == "UNKNOWN_CONTEXT"
    assert "ctx-missing" in excinfo.value.diagnostic


def test_empty_document_is_a_parse_error() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_filing(b"<html><body></body></html>")
    assert excinfo.value.reason_code == "EMPTY_DOCUMENT"
