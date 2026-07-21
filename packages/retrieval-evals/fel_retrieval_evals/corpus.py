"""Corpus resolution seam for the benchmark compiler (M2-023 / T0214a).

Quote resolution and temporal validity depend on the *pinned corpus*: the actual
SEC documents, their acceptance timestamps and their source spans. The compiler
talks to that corpus through the ``Corpus`` protocol so it can run against a JSON
fixture in CI and against the live corpus (a DB-backed implementation, gated on
credentials per issue #58) without changing a validation rule.

``JsonCorpus`` loads a manifest of the form::

    {
      "0001628280-26-038798": {
        "acceptance_timestamp": "2026-05-27T20:05:00Z",
        "spans": [
          {"section": "Financial Highlights - Revenue", "span_id": "…", "text": "…"}
        ]
      }
    }

Resolution is substring containment of the golden quote within a span's text,
scoped to the evidence's declared section. Zero matches is an unresolved anchor;
more than one is an ambiguous anchor — both fail compilation upstream.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol


class Corpus(Protocol):
    """The pinned corpus the compiler resolves golden quotes against."""

    def acceptance_timestamp(self, accession: str) -> datetime | None:
        """SEC acceptance/publication time of a filing, or None if absent."""
        ...

    def resolve_quote(self, accession: str, section: str, quote: str) -> list[str]:
        """Span ids in ``section`` of ``accession`` whose text contains ``quote``."""
        ...


def _parse_ts(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


class JsonCorpus:
    """A ``Corpus`` backed by an in-memory / on-disk JSON manifest (fixture)."""

    def __init__(self, data: dict[str, dict[str, object]]) -> None:
        self._data = data

    @classmethod
    def from_path(cls, path: str | Path) -> JsonCorpus:
        return cls(json.loads(Path(path).read_text()))

    def acceptance_timestamp(self, accession: str) -> datetime | None:
        doc = self._data.get(accession)
        if doc is None:
            return None
        raw = doc.get("acceptance_timestamp")
        return _parse_ts(str(raw)) if raw is not None else None

    def resolve_quote(self, accession: str, section: str, quote: str) -> list[str]:
        # Empty quote would match every span via ``"" in text``; reject up-front.
        if not quote:
            return []
        doc = self._data.get(accession)
        if doc is None:
            return []
        spans = doc.get("spans")
        if not isinstance(spans, list):
            return []
        matches: list[str] = []
        for span in spans:
            if (
                isinstance(span, dict)
                and span.get("section") == section
                and quote in str(span.get("text", ""))
            ):
                matches.append(str(span.get("span_id")))
        return matches


__all__ = ["Corpus", "JsonCorpus"]
