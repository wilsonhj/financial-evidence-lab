"""Compile PR #74's 65-question seed into a checksum-pinned smoke manifest.

The compiler is the executable acceptance gate (ADR-0006 §8, M2-FR-014). The raw
seed is *not* itself the gate: this resolves every golden quote to a unique,
stable evidence id in a pinned corpus and fails closed on anything that would let
a benchmark cheat or leak:

* **Temporal leakage** — a cited document accepted after the record's ``as_of``,
  or a *provisional* same-day midnight cutoff (``T00:00:00`` on the acceptance
  day, which cannot order the filing against the cutoff) — fails.
* **Ambiguous anchor** — a golden quote that resolves to more than one span —
  and **unresolved anchor** — zero spans — both fail.
* **Zero denominator** — a ratio answer ``a/b`` with ``b == 0`` — fails.
* **Negative-case scope** — an unanswerable record that does not declare the
  cutoff-visible corpus it searched (``documents_reviewed``) — fails.

Structural validation (record shape, accession format, numeric parsing, range
normalisation, negative-case scope, zero denominator) runs with no corpus so the
seed can be pinned offline; temporal and quote-resolution checks run when a
``Corpus`` is supplied (a JSON fixture in CI; the live SEC corpus is gated on
credentials per issue #58). The manifest's ``checksum`` is a sha256 over its
canonical body, so an identical seed+corpus always pins to the same digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fel_retrieval_evals.corpus import Corpus, JsonCorpus
from fel_retrieval_evals.models import (
    SCALE_EXPONENTS,
    Evidence,
    ExpectedAnswer,
    Manifest,
    ManifestEntry,
    NumericAnswer,
    TextAnswer,
)

# Stable evidence-id namespace (UUIDv5 over ``accession|section|quote``). Frozen
# so an identical golden anchor always pins to the same evidence id.
EVIDENCE_ID_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_NUMERIC_RE = re.compile(r"^(-?\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$")

_REQUIRED_KEYS = frozenset(
    {
        "id",
        "category",
        "issuer",
        "question",
        "as_of",
        "expected_answer",
        "evidence",
        "documents_reviewed",
        "answerable",
    }
)


@dataclass(frozen=True)
class CompilationViolation:
    """One record-scoped compilation failure."""

    record_id: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.record_id}: [{self.code}] {self.message}"


class CompilationError(RuntimeError):
    """One or more records failed compilation; the manifest is not emitted."""

    def __init__(self, violations: Sequence[CompilationViolation]) -> None:
        self.violations = tuple(violations)
        joined = "\n".join(f"  - {v}" for v in self.violations)
        super().__init__(f"{len(self.violations)} compilation violation(s):\n{joined}")


def load_seed(path: str | Path) -> list[dict[str, Any]]:
    """Load the seed JSONL into a list of raw record dicts."""
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _parse_as_of(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _evidence_id(accession: str, section: str, quote: str) -> str:
    return str(uuid.uuid5(EVIDENCE_ID_NAMESPACE, f"{accession}|{section}|{quote}"))


class _RecordCompiler:
    """Compiles and validates one record, accumulating violations."""

    def __init__(self, record: dict[str, Any], corpus: Corpus | None) -> None:
        self._record = record
        self._corpus = corpus
        self._id = str(record.get("id", "<unknown>"))
        self.violations: list[CompilationViolation] = []

    def _fail(self, code: str, message: str) -> None:
        self.violations.append(CompilationViolation(self._id, code, message))

    def compile(self) -> ManifestEntry | None:
        record = self._record
        missing = _REQUIRED_KEYS - record.keys()
        if missing:
            self._fail("MALFORMED_RECORD", f"missing keys: {sorted(missing)}")
            return None

        answerable = bool(record["answerable"])
        expected = self._compile_expected(answerable, record["expected_answer"])
        evidence = self._compile_evidence(answerable, record["evidence"])
        self._check_documents_reviewed(answerable, record["documents_reviewed"])
        if self._corpus is not None:
            self._check_temporal(record["as_of"], record)

        if self.violations:
            return None
        return ManifestEntry(
            id=self._id,
            category=str(record["category"]),
            issuer={k: str(v) for k, v in dict(record["issuer"]).items()},
            question=str(record["question"]),
            as_of=str(record["as_of"]),
            answerable=answerable,
            expected_answer=expected,
            evidence=tuple(evidence),
            documents_reviewed=tuple(str(a) for a in record["documents_reviewed"]),
        )

    # --- expected answer ---------------------------------------------------
    def _compile_expected(
        self, answerable: bool, raw: dict[str, Any] | None
    ) -> ExpectedAnswer | None:
        if not answerable:
            if raw is not None:
                self._fail("MALFORMED_RECORD", "unanswerable record must have null expected_answer")
            return None
        if raw is None:
            self._fail("MALFORMED_RECORD", "answerable record must have an expected_answer")
            return None
        kind = raw.get("kind")
        if kind == "text":
            text = str(raw.get("text", ""))
            if not text:
                self._fail("MALFORMED_RECORD", "text answer must be non-empty")
                return None
            return TextAnswer(text=text)
        if kind == "numeric":
            return self._compile_numeric(raw)
        self._fail("MALFORMED_RECORD", f"unknown expected_answer kind: {kind!r}")
        return None

    def _compile_numeric(self, raw: dict[str, Any]) -> NumericAnswer | None:
        scale = str(raw.get("scale"))
        if scale not in SCALE_EXPONENTS:
            self._fail("UNKNOWN_SCALE", f"unknown scale {scale!r}")
            return None
        value = str(raw.get("value", ""))
        if "/" in value:
            low = self._compile_ratio(value)
            if low is None:
                return None
            high = low
        else:
            match = _NUMERIC_RE.fullmatch(value)
            if match is None:
                self._fail("INVALID_NUMERIC", f"unparseable numeric value {value!r}")
                return None
            try:
                low = Decimal(match.group(1))
                high = Decimal(match.group(2)) if match.group(2) is not None else low
            except InvalidOperation:  # pragma: no cover - regex already guards
                self._fail("INVALID_NUMERIC", f"unparseable numeric value {value!r}")
                return None
            if low > high:
                self._fail("INVALID_RANGE", f"range low {low} exceeds high {high}")
                return None
        return NumericAnswer(
            low=low,
            high=high,
            unit=str(raw.get("unit", "")),
            scale_exponent=SCALE_EXPONENTS[scale],
            period=str(raw.get("period", "")),
        )

    def _compile_ratio(self, value: str) -> Decimal | None:
        numerator, _, denominator = value.partition("/")
        try:
            num = Decimal(numerator)
            den = Decimal(denominator)
        except InvalidOperation:
            self._fail("INVALID_NUMERIC", f"unparseable ratio {value!r}")
            return None
        if den == 0:
            self._fail("ZERO_DENOMINATOR", f"ratio {value!r} divides by zero")
            return None
        return num / den

    # --- evidence ----------------------------------------------------------
    def _compile_evidence(
        self, answerable: bool, raw_evidence: list[dict[str, Any]]
    ) -> list[Evidence]:
        if not answerable:
            if raw_evidence:
                self._fail("MALFORMED_RECORD", "unanswerable record must have no evidence")
            return []
        if not raw_evidence:
            self._fail("MALFORMED_RECORD", "answerable record must cite evidence")
            return []
        evidence: list[Evidence] = []
        for raw in raw_evidence:
            accession = str(raw.get("accession", ""))
            section = str(raw.get("section", ""))
            quote = str(raw.get("quote", ""))
            if not _ACCESSION_RE.match(accession):
                self._fail("MALFORMED_RECORD", f"malformed accession {accession!r}")
                continue
            span_id = self._resolve(accession, section, quote)
            evidence.append(
                Evidence(
                    accession=accession,
                    form=str(raw.get("form", "")),
                    section=section,
                    quote=quote,
                    evidence_id=_evidence_id(accession, section, quote),
                    span_id=span_id,
                )
            )
        return evidence

    def _resolve(self, accession: str, section: str, quote: str) -> str | None:
        if self._corpus is None:
            return None
        matches = self._corpus.resolve_quote(accession, section, quote)
        if not matches:
            self._fail("UNRESOLVED_ANCHOR", f"quote in {accession}/{section} resolves to no span")
            return None
        if len(matches) > 1:
            self._fail(
                "AMBIGUOUS_ANCHOR",
                f"quote in {accession}/{section} resolves to {len(matches)} spans",
            )
            return None
        return matches[0]

    def _check_documents_reviewed(self, answerable: bool, reviewed: list[Any]) -> None:
        # Negative cases must declare the cutoff-visible corpus they searched.
        if not answerable and not reviewed:
            self._fail(
                "NEGATIVE_SCOPE_MISSING",
                "unanswerable record must declare searched corpus (documents_reviewed)",
            )

    # --- temporal ----------------------------------------------------------
    def _check_temporal(self, as_of_raw: str, record: dict[str, Any]) -> None:
        corpus = self._corpus
        if corpus is None:  # pragma: no cover - caller guards this
            return
        as_of = _parse_as_of(as_of_raw)
        provisional_midnight = (as_of.hour, as_of.minute, as_of.second, as_of.microsecond) == (
            0,
            0,
            0,
            0,
        )
        cited = {e["accession"] for e in record["evidence"]} | set(record["documents_reviewed"])
        for accession in sorted(cited):
            ts = corpus.acceptance_timestamp(accession)
            if ts is None:
                self._fail("UNRESOLVED_ANCHOR", f"{accession} is absent from the pinned corpus")
                continue
            if ts > as_of:
                self._fail(
                    "TEMPORAL_LEAKAGE",
                    f"{accession} accepted {ts.isoformat()} after cutoff {as_of.isoformat()}",
                )
            elif provisional_midnight and ts.date() == as_of.date():
                self._fail(
                    "TEMPORAL_LEAKAGE",
                    f"{accession} accepted on the cutoff day under a provisional midnight cutoff",
                )


def _checksum(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def compile_manifest(
    records: Sequence[dict[str, Any]],
    *,
    corpus: Corpus | None = None,
    corpus_version_id: str | None = None,
) -> Manifest:
    """Compile and validate every record; fail closed on any violation.

    Returns a checksum-pinned :class:`Manifest`. Raises :class:`CompilationError`
    aggregating every violation across all records so a draft seed's gaps surface
    in one pass rather than one at a time.
    """
    seen_ids: set[str] = set()
    entries: list[ManifestEntry] = []
    violations: list[CompilationViolation] = []
    for record in records:
        record_id = str(record.get("id", "<unknown>"))
        if record_id in seen_ids:
            violations.append(
                CompilationViolation(record_id, "MALFORMED_RECORD", "duplicate record id")
            )
            continue
        seen_ids.add(record_id)
        compiler = _RecordCompiler(record, corpus)
        entry = compiler.compile()
        violations.extend(compiler.violations)
        if entry is not None:
            entries.append(entry)
    if violations:
        raise CompilationError(violations)

    manifest = Manifest(
        corpus_version_id=corpus_version_id,
        resolved=corpus is not None,
        entries=tuple(entries),
    )
    return Manifest(
        corpus_version_id=manifest.corpus_version_id,
        resolved=manifest.resolved,
        entries=manifest.entries,
        checksum=_checksum(manifest.body()),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fel_retrieval_evals.compile")
    parser.add_argument("seed", help="path to the seed questions JSONL")
    parser.add_argument("--out", required=True, help="path to write the compiled manifest JSON")
    parser.add_argument("--corpus", help="path to a JSON corpus manifest (enables resolution)")
    parser.add_argument("--corpus-version", help="corpus version id to pin in the manifest")
    args = parser.parse_args(argv)

    records = load_seed(args.seed)
    corpus = JsonCorpus.from_path(args.corpus) if args.corpus else None
    try:
        manifest = compile_manifest(records, corpus=corpus, corpus_version_id=args.corpus_version)
    except CompilationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
    print(
        f"compiled {len(manifest.entries)} questions "
        f"(resolved={manifest.resolved}) -> {out}\nchecksum {manifest.checksum}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
