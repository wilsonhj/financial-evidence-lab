"""Exact-byte, manifest-pinned SEC transport for isolated acceptance runs.

Implements the frozen SecClient protocol without any HTTP fallback. The
manifest and every referenced asset must remain inside the fixture directory;
asset hashes are checked at binding and again on each read.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import cast


def _json_object(raw: bytes) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("fixture JSON has duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("fixture JSON must be a valid object") from exc
    if not isinstance(value, dict):
        raise ValueError("fixture JSON must be an object")
    return cast(dict[str, object], value)


def _cik(value: str) -> str:
    digits = value.removeprefix("CIK")
    if not re.fullmatch(r"[0-9]{1,10}", digits):
        raise ValueError("fixture CIK must contain one to ten digits")
    return digits.zfill(10)


class FixtureSecClient:
    """Read only entries explicitly pinned by ``root/manifest.json``."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._documents: dict[str, tuple[str, str]] = {}
        self._submissions: dict[str, tuple[str, str]] = {}
        manifest = _json_object(self._read_path("manifest.json"))
        if (
            set(manifest) != {"schema_version", "documents", "submissions"}
            or manifest["schema_version"] != "sec-fixture-transport/v1"
        ):
            raise ValueError("unsupported fixture manifest schema")
        for field, identity, lookup in (
            ("documents", "url", self._documents),
            ("submissions", "cik", self._submissions),
        ):
            rows = manifest[field]
            if not isinstance(rows, list):
                raise ValueError("fixture manifest entries must be arrays")
            for row in rows:
                if not isinstance(row, dict) or set(row) != {identity, "path", "sha256"}:
                    raise ValueError("invalid fixture manifest entry")
                if any(not isinstance(value, str) or not value for value in row.values()):
                    raise ValueError("fixture manifest entry fields must be nonempty strings")
                key = _cik(row[identity]) if identity == "cik" else row[identity]
                digest = row["sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError("fixture sha256 must be lowercase hex")
                if key in lookup:
                    raise ValueError("duplicate fixture manifest identity")
                entry = (row["path"], digest)
                self._read_entry(entry)
                lookup[key] = entry

    def _read_path(self, name: str) -> bytes:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("fixture path must be relative and remain inside its root")
        try:
            path = (self._root / relative).resolve()
            if not path.is_relative_to(self._root):
                raise ValueError("fixture path escapes its root")
            return path.read_bytes()
        except (OSError, RuntimeError) as exc:
            raise ValueError("fixture path is not a readable file") from exc

    def _read_entry(self, entry: tuple[str, str]) -> bytes:
        raw = self._read_path(entry[0])
        if hashlib.sha256(raw).hexdigest() != entry[1]:
            raise ValueError("fixture sha256 mismatch")
        return raw

    def fetch_document(self, url: str) -> bytes:
        entry = self._documents.get(url)
        if entry is None:
            raise ValueError("document URL not in fixture manifest")
        return self._read_entry(entry)

    def submissions(self, cik: str) -> dict[str, object]:
        entry = self._submissions.get(_cik(cik))
        if entry is None:
            raise ValueError("CIK not in fixture manifest")
        return _json_object(self._read_entry(entry))
