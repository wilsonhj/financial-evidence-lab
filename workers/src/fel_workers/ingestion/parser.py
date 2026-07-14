"""HTML/iXBRL filing parser (T0103).

Stdlib-only (``html.parser``); no new root dependency. Produces:

- a canonical whitespace-normalized text rendering with deterministic
  character offsets;
- a section hierarchy (heading path + document order) from h1-h6 headings;
- stable source spans (contract source-span/v1): deterministic UUIDv5 ids,
  character offsets into the canonical text, and a sha256 text hash;
- extracted tables (caption, header row, body rows) with nested-table
  support — both the outer and inner tables are emitted, outer rows intact;
- raw inline-XBRL facts (nesting supported via a fact stack) with their
  contexts (period + dimensions) and units. Nil or content-empty facts
  (e.g. self-closing ``<ix:nonFraction xsi:nil="true"/>``) never fail the
  filing: they are skipped and recorded as per-fact diagnostics on the
  :class:`ParsedDocument` (explicit-nil representation was rejected because
  downstream fact values are NOT NULL decimal strings by contract).

Malformed sources raise :class:`ParseError` carrying a stable reason code
and an actionable diagnostic; the pipeline turns that into a quarantine row
(T0106, FR-ING-007).

Content hashes use the repository-wide ``sha256:<hex>`` format everywhere
(same format the DB CHECK constraints expect); the pipeline hashes the raw
bytes once and passes the hash through.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from types import MappingProxyType

from fel_workers.ingestion.errors import ParseError, ReasonCode

__all__ = [
    "PARSER_VERSION",
    "ID_NAMESPACE",
    "ROOT_HEADING",
    "ParseError",
    "Section",
    "SourceSpan",
    "ExtractedTable",
    "XbrlContext",
    "InlineFact",
    "ParsedDocument",
    "parse_filing",
    "sha256_hex",
    "text_hash",
]

PARSER_VERSION = "fel-parser/1.0.0"

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://financial-evidence-lab.dev/ingestion")

_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_TAGS = frozenset({"p", "div", "li", "tr", "table", "caption", *_HEADING_LEVELS})
ROOT_HEADING = "(document)"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_hash(text: str) -> str:
    """Contract source-span/v1 text hash: ``sha256:<hex>`` of UTF-8 text."""
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Section:
    id: str
    parent_id: str | None
    heading: str
    heading_path: tuple[str, ...]
    order: int
    start_char: int
    end_char: int


@dataclass(frozen=True)
class SourceSpan:
    """Contract source-span/v1 plus the covered text (in-memory only)."""

    id: str
    section_id: str
    start_char: int
    end_char: int
    text_hash: str
    text: str


@dataclass(frozen=True)
class ExtractedTable:
    id: str
    section_id: str
    order: int
    caption: str | None
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class XbrlContext:
    id: str
    instant: date | None
    start: date | None
    end: date | None
    dimensions: Mapping[str, str]


@dataclass(frozen=True)
class InlineFact:
    """Raw ix:nonFraction occurrence before normalization (T0104 input)."""

    concept: str
    context_ref: str
    unit_ref: str
    scale: int
    decimals: str | None
    sign: str | None
    format: str | None
    """iXBRL transformation registry format (e.g. ``ixt:num-comma-decimal``);
    None means the plain default numeric rendering."""
    raw_text: str
    span_id: str
    section_id: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class ParsedDocument:
    content_hash: str
    """``sha256:<hex>`` of the raw source bytes (repository-wide format)."""
    parser_version: str
    text: str
    sections: tuple[Section, ...]
    spans: tuple[SourceSpan, ...]
    tables: tuple[ExtractedTable, ...]
    contexts: Mapping[str, XbrlContext]
    units: Mapping[str, str]
    facts: tuple[InlineFact, ...]
    diagnostics: tuple[str, ...] = ()
    """Per-fact non-fatal diagnostics (e.g. skipped nil/empty facts)."""


@dataclass
class _MutableSection:
    heading: str
    heading_path: tuple[str, ...]
    level: int
    order: int
    start_char: int
    parent_index: int | None
    end_char: int = 0


@dataclass
class _RawFactState:
    attrs: dict[str, str | None]
    start: int
    end: int
    section_index: int


@dataclass
class _TableState:
    order: int
    section_index: int
    caption: str | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    current_row: list[str] | None = None
    current_row_is_header: bool = True
    cell_parts: list[str] | None = None
    in_caption: bool = False


class _FilingHTMLParser(HTMLParser):
    """Single-pass walk building canonical text, sections, spans, and facts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._pos = 0
        self.sections: list[_MutableSection] = [
            _MutableSection(
                heading=ROOT_HEADING,
                heading_path=(ROOT_HEADING,),
                level=0,
                order=0,
                start_char=0,
                parent_index=None,
            )
        ]
        self._section_stack: list[int] = [0]
        self.paragraph_ranges: list[tuple[int, int, int]] = []  # (section, start, end)
        self.tables: list[_TableState] = []
        # Nested-table support: a stack so an inner <table> never drops the
        # outer one (finding: nested tables lost the outer table's rows).
        self._table_stack: list[_TableState] = []
        self._table_count = 0
        self.raw_facts: list[_RawFactState] = []
        # Nested ix:nonFraction support: a stack so an inner fact never
        # drops the outer fact.
        self._fact_stack: list[tuple[dict[str, str | None], int]] = []
        self._heading_start: int | None = None
        self._heading_level = 0
        self._block_start: int | None = None
        # iXBRL header (hidden resources) state.
        self._in_ix_header = False
        self.contexts: dict[str, XbrlContext] = {}
        self.units: dict[str, str] = {}
        self._context_id: str | None = None
        self._context_period: dict[str, date] = {}
        self._context_dims: dict[str, str] = {}
        self._unit_id: str | None = None
        self._capture_kind: str | None = None
        self._capture_parts: list[str] = []
        self._capture_dimension: str | None = None

    # -- canonical text helpers ------------------------------------------------

    def _append(self, piece: str) -> None:
        self._parts.append(piece)
        self._pos += len(piece)

    def _append_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._parts and not self._parts[-1].endswith((" ", "\n")):
            self._append(" ")
        self._append(normalized)

    def _newline(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._append("\n")

    @property
    def canonical_text(self) -> str:
        return "".join(self._parts)

    # -- HTMLParser hooks --------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value for name, value in attrs}
        if tag == "ix:header":
            self._in_ix_header = True
            return
        if self._in_ix_header:
            self._start_header_tag(tag, attr_map)
            return
        if tag in _BLOCK_TAGS:
            self._newline()
        if tag in _HEADING_LEVELS:
            self._heading_start = self._pos
            self._heading_level = _HEADING_LEVELS[tag]
        elif tag == "p":
            self._block_start = self._pos
        elif tag == "table":
            self._table_stack.append(
                _TableState(order=self._table_count, section_index=self._section_stack[-1])
            )
            self._table_count += 1
        elif self._table_stack and tag == "caption":
            table = self._table_stack[-1]
            table.in_caption = True
            table.cell_parts = []
        elif self._table_stack and tag == "tr":
            table = self._table_stack[-1]
            table.current_row = []
            table.current_row_is_header = True
        elif self._table_stack and tag in ("td", "th"):
            table = self._table_stack[-1]
            table.cell_parts = []
            if tag == "td":
                table.current_row_is_header = False
        elif tag == "ix:nonfraction":
            self._fact_stack.append(
                (
                    {
                        "name": attr_map.get("name"),
                        "contextref": attr_map.get("contextref"),
                        "unitref": attr_map.get("unitref"),
                        "scale": attr_map.get("scale"),
                        "decimals": attr_map.get("decimals"),
                        "sign": attr_map.get("sign"),
                        "format": attr_map.get("format"),
                        "nil": attr_map.get("xsi:nil"),
                    },
                    self._pos,
                )
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "ix:header":
            self._in_ix_header = False
            return
        if self._in_ix_header:
            self._end_header_tag(tag)
            return
        if tag in _HEADING_LEVELS and self._heading_start is not None:
            self._close_heading()
        elif tag == "p" and self._block_start is not None:
            end = self._pos
            if end > self._block_start:
                self.paragraph_ranges.append((self._section_stack[-1], self._block_start, end))
            self._block_start = None
        elif self._table_stack and tag == "caption":
            table = self._table_stack[-1]
            table.caption = "".join(table.cell_parts or []).strip() or None
            table.cell_parts = None
            table.in_caption = False
        elif self._table_stack and tag in ("td", "th"):
            table = self._table_stack[-1]
            if table.current_row is not None:
                table.current_row.append("".join(table.cell_parts or []).strip())
            table.cell_parts = None
        elif self._table_stack and tag == "tr":
            table = self._table_stack[-1]
            row = table.current_row
            if row is not None:
                if table.current_row_is_header and not table.headers:
                    table.headers = row
                else:
                    table.rows.append(row)
            table.current_row = None
        elif self._table_stack and tag == "table":
            # Pop the innermost table; the outer table (if any) resumes with
            # its rows intact.
            self.tables.append(self._table_stack.pop())
        elif tag == "ix:nonfraction" and self._fact_stack:
            attr_map, start = self._fact_stack.pop()
            self.raw_facts.append(
                _RawFactState(
                    attrs=attr_map,
                    start=start,
                    end=self._pos,
                    section_index=self._section_stack[-1],
                )
            )
        if tag in _BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._in_ix_header:
            if self._capture_kind is not None:
                self._capture_parts.append(data)
            return
        if self._table_stack and self._table_stack[-1].cell_parts is not None:
            cell_parts = self._table_stack[-1].cell_parts
            normalized = " ".join(data.split())
            if normalized:
                if cell_parts and not cell_parts[-1].endswith(" "):
                    cell_parts.append(" ")
                cell_parts.append(normalized)
        self._append_data(data)

    # -- headings / sections -------------------------------------------------------

    def _close_heading(self) -> None:
        start = self._heading_start if self._heading_start is not None else self._pos
        heading = self.canonical_text[start : self._pos].strip()
        level = self._heading_level
        self._heading_start = None
        if not heading:
            return
        while len(self._section_stack) > 1 and (
            self.sections[self._section_stack[-1]].level >= level
        ):
            self._section_stack.pop()
        parent_index = self._section_stack[-1]
        section = _MutableSection(
            heading=heading,
            heading_path=(*self.sections[parent_index].heading_path, heading),
            level=level,
            order=len(self.sections),
            start_char=start,
            parent_index=parent_index,
        )
        self.sections.append(section)
        self._section_stack.append(section.order)

    # -- iXBRL header (contexts and units) ------------------------------------------

    def _start_header_tag(self, tag: str, attr_map: dict[str, str | None]) -> None:
        if tag == "xbrli:context":
            self._context_id = attr_map.get("id")
            self._context_period = {}
            self._context_dims = {}
        elif tag in ("xbrli:instant", "xbrli:startdate", "xbrli:enddate"):
            self._capture_kind = tag.removeprefix("xbrli:")
            self._capture_parts = []
        elif tag == "xbrldi:explicitmember":
            self._capture_kind = "dimension-member"
            self._capture_parts = []
            self._capture_dimension = attr_map.get("dimension")
        elif tag == "xbrli:unit":
            self._unit_id = attr_map.get("id")
        elif tag == "xbrli:measure":
            self._capture_kind = "measure"
            self._capture_parts = []

    def _end_header_tag(self, tag: str) -> None:
        captured = "".join(self._capture_parts).strip()
        if tag in ("xbrli:instant", "xbrli:startdate", "xbrli:enddate"):
            kind = tag.removeprefix("xbrli:")
            try:
                self._context_period[kind] = date.fromisoformat(captured)
            except ValueError as exc:
                raise ParseError(
                    ReasonCode.INVALID_PERIOD_DATE,
                    f"context '{self._context_id}' has unparseable {kind} "
                    f"value {captured!r}; expected an ISO date",
                ) from exc
            self._capture_kind = None
        elif tag == "xbrldi:explicitmember":
            if self._capture_dimension and captured:
                self._context_dims[self._capture_dimension] = captured
            self._capture_kind = None
            self._capture_dimension = None
        elif tag == "xbrli:measure":
            if self._unit_id and captured:
                self.units[self._unit_id] = captured
            self._capture_kind = None
        elif tag == "xbrli:context":
            if self._context_id:
                self.contexts[self._context_id] = XbrlContext(
                    id=self._context_id,
                    instant=self._context_period.get("instant"),
                    start=self._context_period.get("startdate"),
                    end=self._context_period.get("enddate"),
                    dimensions=MappingProxyType(dict(self._context_dims)),
                )
            self._context_id = None
        elif tag == "xbrli:unit":
            self._unit_id = None


def _trim_range(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a range so it covers no leading/trailing whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def parse_filing(
    raw: bytes, *, id_seed: str | None = None, content_hash: str | None = None
) -> ParsedDocument:
    """Parse filing bytes into hierarchy, spans, tables, and raw iXBRL facts.

    ``id_seed`` scopes the deterministic UUIDv5 identifiers; the pipeline
    passes the document-version id so section/span ids are unique per parsed
    version while staying byte-for-byte stable across identical reruns. The
    default seed (content hash + parser version) keeps standalone parses
    reproducible.

    ``content_hash`` (``sha256:<hex>``) lets the caller pass the hash it
    already computed so the bytes are hashed exactly once end-to-end; when
    omitted the parser computes it.
    """
    if content_hash is None:
        content_hash = "sha256:" + sha256_hex(raw)
    seed = id_seed if id_seed is not None else f"{content_hash}|{PARSER_VERSION}"
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(
            ReasonCode.ENCODING_ERROR,
            f"source is not valid UTF-8 (byte offset {exc.start}); "
            "re-fetch the document or register the correct encoding",
        ) from exc

    parser = _FilingHTMLParser()
    parser.feed(html)
    parser.close()

    text = parser.canonical_text
    if not text.strip():
        raise ParseError(
            ReasonCode.EMPTY_DOCUMENT,
            "no textual content found after parsing; the source is likely "
            "truncated or not an HTML filing",
        )

    total = len(text)
    section_ids: list[str] = []
    sections: list[Section] = []
    ordered = parser.sections
    for section in ordered:
        section_ids.append(str(uuid.uuid5(ID_NAMESPACE, f"{seed}|section|{section.order}")))
    for index, section in enumerate(ordered):
        next_start = ordered[index + 1].start_char if index + 1 < len(ordered) else total
        parent_id = section_ids[section.parent_index] if section.parent_index is not None else None
        sections.append(
            Section(
                id=section_ids[index],
                parent_id=parent_id,
                heading=section.heading,
                heading_path=section.heading_path,
                order=section.order,
                start_char=section.start_char,
                end_char=next_start,
            )
        )

    spans: list[SourceSpan] = []
    for section_index, start, end in parser.paragraph_ranges:
        start, end = _trim_range(text, start, end)
        if end <= start:
            continue
        covered = text[start:end]
        span_id = str(uuid.uuid5(ID_NAMESPACE, f"{seed}|span|{start}|{end}"))
        spans.append(
            SourceSpan(
                id=span_id,
                section_id=section_ids[section_index],
                start_char=start,
                end_char=end,
                text_hash=text_hash(covered),
                text=covered,
            )
        )
    span_by_range = {(span.start_char, span.end_char): span.id for span in spans}

    facts: list[InlineFact] = []
    diagnostics: list[str] = []
    # Stable document order regardless of nesting (inner facts close first).
    ordered_raw_facts = sorted(parser.raw_facts, key=lambda f: (f.start, -f.end))
    for raw_fact in ordered_raw_facts:
        attrs = raw_fact.attrs
        section_index = raw_fact.section_index
        start, end = _trim_range(text, raw_fact.start, raw_fact.end)
        concept = attrs.get("name")
        is_nil = (attrs.get("nil") or "").strip().lower() in ("true", "1")
        if is_nil or end <= start:
            # A nil or content-empty fact (commonly a self-closing element)
            # must not quarantine the filing: skip it and record a per-fact
            # diagnostic instead (see module docstring for the rationale).
            diagnostics.append(
                f"skipped {'nil' if is_nil else 'empty'} inline fact "
                f"'{concept or '(unnamed)'}' at chars {start}-{end}"
            )
            continue
        context_ref = attrs.get("contextref")
        unit_ref = attrs.get("unitref")
        if not concept or not context_ref or not unit_ref:
            raise ParseError(
                ReasonCode.INCOMPLETE_FACT,
                f"inline fact at chars {start}-{end} is missing one of "
                "name/contextRef/unitRef; the iXBRL markup is malformed",
            )
        if context_ref not in parser.contexts:
            raise ParseError(
                ReasonCode.UNKNOWN_CONTEXT,
                f"inline fact '{concept}' references undefined context "
                f"'{context_ref}'; the ix:header resources are missing or "
                "truncated",
            )
        if unit_ref not in parser.units:
            raise ParseError(
                ReasonCode.UNKNOWN_UNIT,
                f"inline fact '{concept}' references undefined unit "
                f"'{unit_ref}'; the ix:header resources are missing or "
                "truncated",
            )
        scale_text = attrs.get("scale")
        try:
            scale = int(scale_text) if scale_text else 0
        except ValueError as exc:
            raise ParseError(
                ReasonCode.INVALID_SCALE,
                f"inline fact '{concept}' has non-integer scale {scale_text!r}",
            ) from exc
        if (start, end) not in span_by_range:
            covered = text[start:end]
            span_id = str(uuid.uuid5(ID_NAMESPACE, f"{seed}|span|{start}|{end}"))
            spans.append(
                SourceSpan(
                    id=span_id,
                    section_id=section_ids[section_index],
                    start_char=start,
                    end_char=end,
                    text_hash=text_hash(covered),
                    text=covered,
                )
            )
            span_by_range[(start, end)] = span_id
        facts.append(
            InlineFact(
                concept=concept,
                context_ref=context_ref,
                unit_ref=unit_ref,
                scale=scale,
                decimals=attrs.get("decimals"),
                sign=attrs.get("sign"),
                format=attrs.get("format"),
                raw_text=text[start:end],
                span_id=span_by_range[(start, end)],
                section_id=section_ids[section_index],
                start_char=start,
                end_char=end,
            )
        )

    tables: list[ExtractedTable] = []
    # Stable document order regardless of nesting (inner tables close first).
    for table in sorted(parser.tables, key=lambda t: t.order):
        table_id = str(uuid.uuid5(ID_NAMESPACE, f"{seed}|table|{table.order}"))
        tables.append(
            ExtractedTable(
                id=table_id,
                section_id=section_ids[table.section_index],
                order=table.order,
                caption=table.caption,
                headers=tuple(table.headers),
                rows=tuple(tuple(row) for row in table.rows),
            )
        )

    return ParsedDocument(
        content_hash=content_hash,
        parser_version=PARSER_VERSION,
        text=text,
        sections=tuple(sections),
        spans=tuple(spans),
        tables=tuple(tables),
        contexts=MappingProxyType(dict(parser.contexts)),
        units=MappingProxyType(dict(parser.units)),
        facts=tuple(facts),
        diagnostics=tuple(diagnostics),
    )
