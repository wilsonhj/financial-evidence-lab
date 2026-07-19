"""Minimal finance-aware candidates from a parsed-corpus view (M2-010)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PassageCandidate:
    source_span_id: str
    section_id: str
    start_char: int
    end_char: int
    content: str
    text_hash: str
    heading_path: tuple[str, ...]


@dataclass(frozen=True)
class FactCandidate:
    financial_fact_id: str
    source_span_id: str
    section_id: str
    start_char: int
    end_char: int
    content: str
    text_hash: str
    heading_path: tuple[str, ...]
    period: str | None


@dataclass(frozen=True)
class TableRowCandidate:
    table_id: str
    table_row_index: int
    source_span_id: str | None
    section_id: str
    start_char: int | None
    end_char: int | None
    content: str | None
    text_hash: str | None
    heading_path: tuple[str, ...]


def _path(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(part) for part in value)
    return (str(value),)


def passage_candidates(corpus: Mapping[str, Any]) -> list[PassageCandidate]:
    """One passage candidate per hash-verifiable source span."""
    out: list[PassageCandidate] = []
    for span in corpus.get("source_spans", []):
        out.append(
            PassageCandidate(
                source_span_id=str(span["id"]),
                section_id=str(span["section_id"]),
                start_char=int(span["start_char"]),
                end_char=int(span["end_char"]),
                content=str(span["text"]),
                text_hash=str(span["text_hash"]),
                heading_path=_path(span.get("heading_path")),
            )
        )
    return out


def fact_candidates(corpus: Mapping[str, Any]) -> list[FactCandidate]:
    spans = {str(s["id"]): s for s in corpus.get("source_spans", [])}
    out: list[FactCandidate] = []
    for fact in corpus.get("financial_facts", []):
        span = spans.get(str(fact["source_span_id"]))
        if span is None:
            continue
        out.append(
            FactCandidate(
                financial_fact_id=str(fact["id"]),
                source_span_id=str(span["id"]),
                section_id=str(span["section_id"]),
                start_char=int(span["start_char"]),
                end_char=int(span["end_char"]),
                content=str(span["text"]),
                text_hash=str(span["text_hash"]),
                heading_path=_path(span.get("heading_path")),
                period=str(fact["period"]) if fact.get("period") is not None else None,
            )
        )
    return out


def table_row_candidates(corpus: Mapping[str, Any]) -> list[TableRowCandidate]:
    spans = {str(s["id"]): s for s in corpus.get("source_spans", [])}
    out: list[TableRowCandidate] = []
    for table in corpus.get("tables", []):
        table_id = str(table["id"])
        section_id = str(table["section_id"])
        heading = _path(table.get("heading_path"))
        rows = table.get("rows", [])
        for index, row in enumerate(rows):
            span_id = row.get("source_span_id")
            span = spans.get(str(span_id)) if span_id is not None else None
            if span is None:
                out.append(
                    TableRowCandidate(
                        table_id=table_id,
                        table_row_index=index,
                        source_span_id=str(span_id) if span_id is not None else None,
                        section_id=section_id,
                        start_char=None,
                        end_char=None,
                        content=None,
                        text_hash=None,
                        heading_path=heading,
                    )
                )
                continue
            out.append(
                TableRowCandidate(
                    table_id=table_id,
                    table_row_index=index,
                    source_span_id=str(span["id"]),
                    section_id=str(span["section_id"]),
                    start_char=int(span["start_char"]),
                    end_char=int(span["end_char"]),
                    content=str(span["text"]),
                    text_hash=str(span["text_hash"]),
                    heading_path=heading or _path(span.get("heading_path")),
                )
            )
    return out
