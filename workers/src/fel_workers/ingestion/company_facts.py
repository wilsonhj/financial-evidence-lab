"""SEC companyfacts ingestion as stored corpus documents (FR-ING-001, issue #83).

Stored-document ruling (integration lead, 2026-07-14): every fetched
companyfacts JSON payload is a REAL content-addressed corpus document —
``form='COMPANYFACTS'``, ``mime_type='application/json'``, ``published_at``
= the fetch instant — flowing through the existing raw store, ledger, and
persistence patterns. Its facts carry ordinary source spans into the
document's own canonical text (a deterministic rendering of the JSON), so
``source_span_id NOT NULL`` and citation-integrity-by-code hold with zero
exceptions.

Design points, all mandated by the ruling:

- **Snapshot-scoped accessions**: ``COMPANYFACTS-<cik10>-<UTC date>-<hash8>``.
  The content-hash suffix makes an intra-day refetch of a MUTATED payload a
  new document instead of a ``DIVERGENT_ACCESSION_CONTENT`` quarantine,
  while a byte-identical refetch still dedupes through the content-keyed
  job identity (ledger no-op).
- **Dedicated parser/normalizer versions**: ``ingest_filing``'s
  ``parse_filing`` is HTML/iXBRL-only; this module owns the JSON channel
  end to end with its own version strings.
- **Canonical text = the stored JSON in a stable rendering** (sorted keys,
  fixed indentation, decimal-faithful numbers). Sections: one child per
  taxonomy concept (``heading_path = ['(document)', taxonomy, concept]``)
  under the root; one span per unit/period observation slicing the exact
  one-line JSON fragment, ``text_hash`` over that slice.
- **Restatement isolation, both directions**: normalization here NEVER
  consults prior facts (``restates`` is always NULL), and the filing
  pipeline's ``_prior_canonical_facts`` excludes ``form='COMPANYFACTS'``
  documents. Cross-channel value reconciliation is a QA-report concern.
  Observation provenance (``accn``/``form``/``fy``/``fp``/``frame``) enters
  the fact ``dimensions``, so the same concept/period reported by two
  source filings keys distinctly — real payloads carry restated values for
  the same period side by side, and without the provenance key they would
  collide as INCONSISTENT_DUPLICATE.
- **mypy-strict-safe dispatch**: :class:`CompanyFactsSecClient` is a
  workers-local ``@runtime_checkable`` extension of the frozen
  ``SecClient`` protocol; the consumer narrows via ``isinstance`` and
  ``queue.fail``s the job when the bound client lacks the capability.

Values are decimal strings end to end (``parse_float=Decimal``; non-finite
constants are rejected fail-closed at parse time). Text-shaped, boolean,
null, or missing ``val`` observations never fail the snapshot: they keep
their span but are skipped with a per-observation diagnostic (mirrors the
filing parser's nil-fact policy — fact values are NOT NULL decimal strings
by contract).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import psycopg
from psycopg.rows import dict_row

from fel_providers.interfaces import SecClient, StorageProvider
from fel_workers import queue
from fel_workers.ingestion.errors import (
    IngestError,
    NormalizationError,
    ParseError,
    ReasonCode,
)
from fel_workers.ingestion.parser import ID_NAMESPACE, ROOT_HEADING, Section, SourceSpan, text_hash
from fel_workers.ingestion.pipeline import (
    COMPANY_FACTS_FORM,
    IngestionOutcome,
    _noop_outcome,
    _record_quarantine,
    canonical_text_address,
    job_key,
)
from fel_workers.ingestion.raw_store import (
    StoredDocument,
    content_address,
    document_id_for_accession,
    store_raw_document,
)
from fel_workers.ingestion.sec_client import company_facts_url, normalize_cik
from fel_workers.ingestion.xbrl import NormalizedFact, decimal_str, fact_key, map_unit

__all__ = [
    "COMPANY_FACTS_FORM",
    "COMPANY_FACTS_MIME_TYPE",
    "COMPANY_FACTS_PARSER_VERSION",
    "COMPANY_FACTS_NORMALIZER_VERSION",
    "JOB_KIND_SEC_COMPANY_FACTS",
    "CompanyFactsSecClient",
    "CompanyFactsObservation",
    "ParsedCompanyFacts",
    "canonical_company_facts_bytes",
    "company_facts_accession",
    "entity_id_for_cik",
    "enqueue_company_facts",
    "handle_sec_company_facts",
    "ingest_company_facts",
    "normalize_company_facts",
    "parse_company_facts",
]

COMPANY_FACTS_MIME_TYPE = "application/json"
COMPANY_FACTS_PARSER_VERSION = "fel-companyfacts-parser/1.0.0"
COMPANY_FACTS_NORMALIZER_VERSION = "fel-companyfacts-normalizer/1.0.0"
JOB_KIND_SEC_COMPANY_FACTS = "sec_company_facts"

# Observation keys copied into fact dimensions as reporting provenance (see
# module docstring: they keep same-period values from different source
# filings on distinct fact keys).
_PROVENANCE_KEYS = ("accn", "form", "fy", "fp", "frame")


@runtime_checkable
class CompanyFactsSecClient(SecClient, Protocol):
    """Workers-local capability extension of the frozen SecClient protocol.

    ``packages/providers`` is contract-frozen; this Protocol adds the
    companyfacts fetch WITHOUT touching it. The consumer narrows the bound
    client via ``isinstance`` at dispatch time (``@runtime_checkable``
    checks method presence) and fails the job when the capability is
    missing — ``run_worker(sec: SecClient)`` stays unchanged.
    """

    def company_facts(self, cik: str) -> dict[str, object]: ...


def entity_id_for_cik(cik: str) -> str:
    """Deterministic entity id for an SEC issuer (uuid5 over the CIK)."""
    return str(uuid.uuid5(ID_NAMESPACE, f"entity|{normalize_cik(cik)}"))


def company_facts_accession(cik: str, fetched_at: datetime, content_hash: str) -> str:
    """Snapshot-scoped accession: ``COMPANYFACTS-<cik10>-<UTC date>-<hash8>``.

    The first 8 hex chars of the content hash make a mutated intra-day
    refetch a NEW document (never a divergence quarantine); a byte-identical
    refetch maps to the same accession and dedupes via the job ledger.
    """
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware (UTC snapshot dating)")
    day = fetched_at.astimezone(UTC).date().isoformat()
    digest = content_hash.removeprefix("sha256:")[:8]
    return f"{COMPANY_FACTS_FORM}-{normalize_cik(cik)}-{day}-{digest}"


def canonical_company_facts_bytes(payload: dict[str, object]) -> bytes:
    """Deterministic bytes for a fetched companyfacts payload.

    The client protocol returns the decoded JSON object; these bytes are its
    stable serialization (sorted keys, compact separators, Decimal-faithful
    numbers), so byte identity equals semantic identity of the payload — key
    order or whitespace churn in the HTTP response never mints a new
    document. Callers MUST decode with ``parse_float=Decimal`` (never IEEE
    float): binary floats are rejected here so a float-decoded live client
    cannot silently corrupt the stored corpus.
    """
    return _compact_json_value(payload).encode()


def _compact_json_value(value: object) -> str:
    """Compact JSON (no spaces) with Decimal-as-number rendering."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return decimal_str(value)
    if isinstance(value, int):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        raise TypeError(
            "companyfacts canonical bytes reject IEEE-754 floats; decode "
            "with json.loads(..., parse_float=Decimal) before serializing"
        )
    if isinstance(value, list):
        return "[" + ",".join(_compact_json_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                f"{json.dumps(str(key), ensure_ascii=False)}:{_compact_json_value(value[key])}"
                for key in sorted(value)
            )
            + "}"
        )
    raise TypeError(f"companyfacts canonical bytes cannot serialize {type(value).__name__}")


@dataclass(frozen=True)
class CompanyFactsObservation:
    """One numeric unit/period observation from the payload."""

    taxonomy: str
    concept: str
    """Qualified concept name (``taxonomy:LocalName``)."""
    label: str | None
    unit: str
    value: Decimal
    period_start: date | None
    """Set for duration observations; None for instants."""
    period_end: date
    dimensions: Mapping[str, str]
    """Reporting provenance (accn/form/fy/fp/frame) — see module docstring."""
    span_id: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class ParsedCompanyFacts:
    """Canonical rendering plus hierarchy, spans, and numeric observations."""

    content_hash: str
    parser_version: str
    text: str
    sections: tuple[Section, ...]
    spans: tuple[SourceSpan, ...]
    observations: tuple[CompanyFactsObservation, ...]
    diagnostics: tuple[str, ...] = ()


def _reject_non_finite(constant: str) -> Decimal:
    raise NormalizationError(
        ReasonCode.NONFINITE_FACT_VALUE,
        f"companyfacts payload contains the non-finite JSON constant "
        f"{constant!r}; NaN/Infinity are never storable",
    )


def _render_json_value(value: object) -> str:
    """Deterministic single-line JSON rendering (sorted keys, Decimal-aware)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return decimal_str(value)
    if isinstance(value, int):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_render_json_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{json.dumps(str(key), ensure_ascii=False)}: {_render_json_value(value[key])}"
                for key in sorted(value)
            )
            + "}"
        )
    raise ParseError(  # pragma: no cover — floats cannot appear (parse_float=Decimal)
        ReasonCode.MALFORMED_JSON,
        f"companyfacts payload contains an unrenderable value of type {type(value).__name__}",
    )


def _iso_date(value: object, *, concept: str, field: str) -> date:
    if not isinstance(value, str):
        raise ParseError(
            ReasonCode.INVALID_PERIOD_STRUCTURE,
            f"companyfacts observation for '{concept}' has a non-string "
            f"{field!r} period field ({value!r}); every observation must "
            "carry ISO period dates",
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ParseError(
            ReasonCode.INVALID_PERIOD_DATE,
            f"companyfacts observation for '{concept}' has unparseable "
            f"{field} value {value!r}; expected an ISO date",
        ) from exc


class _CanonicalBuilder:
    """Position-tracking writer for the canonical JSON rendering.

    Because this module both RENDERS the canonical text and RECORDS the
    section/span character offsets while rendering, span slices are exact by
    construction and re-verify against the persisted text forever.
    """

    def __init__(self, seed: str) -> None:
        self._seed = seed
        self._parts: list[str] = []
        self.pos = 0
        self.sections: list[Section] = []
        self.spans: list[SourceSpan] = []
        self.observations: list[CompanyFactsObservation] = []
        self.diagnostics: list[str] = []
        self.root_id = str(uuid.uuid5(ID_NAMESPACE, f"{seed}|section|0"))

    def emit(self, piece: str) -> None:
        self._parts.append(piece)
        self.pos += len(piece)

    @property
    def text(self) -> str:
        return "".join(self._parts)

    # -- structural walk -----------------------------------------------------

    def render_document(self, payload: dict[str, object]) -> None:
        self.emit("{\n")
        keys = sorted(payload)
        for index, key in enumerate(keys):
            self.emit(f"  {json.dumps(key, ensure_ascii=False)}: ")
            if key == "facts":
                self._render_facts(payload[key])
            else:
                self.emit(_render_json_value(payload[key]))
            self.emit(",\n" if index < len(keys) - 1 else "\n")
        self.emit("}")

    def _render_facts(self, facts: object) -> None:
        if not isinstance(facts, dict):
            raise ParseError(
                ReasonCode.MALFORMED_JSON,
                "companyfacts 'facts' member is not a JSON object; the "
                "payload does not have the companyfacts API shape",
            )
        if not facts:
            self.emit("{}")
            return
        self.emit("{\n")
        taxonomies = sorted(facts)
        for t_index, taxonomy in enumerate(taxonomies):
            concepts = facts[taxonomy]
            if not isinstance(concepts, dict):
                raise ParseError(
                    ReasonCode.MALFORMED_JSON,
                    f"companyfacts taxonomy {taxonomy!r} is not a JSON " "object of concepts",
                )
            self.emit(f"    {json.dumps(taxonomy, ensure_ascii=False)}: {{\n")
            names = sorted(concepts)
            for c_index, name in enumerate(names):
                self._render_concept(taxonomy, name, concepts[name])
                self.emit(",\n" if c_index < len(names) - 1 else "\n")
            self.emit("    }")
            self.emit(",\n" if t_index < len(taxonomies) - 1 else "\n")
        self.emit("  }")

    def _render_concept(self, taxonomy: str, name: str, concept: object) -> None:
        if not isinstance(concept, dict):
            raise ParseError(
                ReasonCode.MALFORMED_JSON,
                f"companyfacts concept {taxonomy}:{name} is not a JSON object",
            )
        label = concept.get("label")
        label_text = label if isinstance(label, str) else None
        self.emit("      ")
        start = self.pos
        order = len(self.sections) + 1  # root occupies ord 0
        section_id = str(uuid.uuid5(ID_NAMESPACE, f"{self._seed}|section|{order}"))
        self.emit(f"{json.dumps(name, ensure_ascii=False)}: {{\n")
        keys = sorted(concept)
        for index, key in enumerate(keys):
            self.emit(f"        {json.dumps(key, ensure_ascii=False)}: ")
            if key == "units":
                self._render_units(taxonomy, name, label_text, section_id, concept[key])
            else:
                self.emit(_render_json_value(concept[key]))
            self.emit(",\n" if index < len(keys) - 1 else "\n")
        self.emit("      }")
        self.sections.append(
            Section(
                id=section_id,
                parent_id=self.root_id,
                heading=name,
                heading_path=(ROOT_HEADING, taxonomy, name),
                order=order,
                start_char=start,
                end_char=self.pos,
            )
        )

    def _render_units(
        self,
        taxonomy: str,
        name: str,
        label: str | None,
        section_id: str,
        units: object,
    ) -> None:
        qualified = f"{taxonomy}:{name}"
        if not isinstance(units, dict):
            raise ParseError(
                ReasonCode.MALFORMED_JSON,
                f"companyfacts concept {qualified} has a non-object 'units' member",
            )
        if not units:
            self.emit("{}")
            return
        self.emit("{\n")
        unit_names = sorted(units)
        for u_index, unit in enumerate(unit_names):
            observations = units[unit]
            if not isinstance(observations, list):
                raise ParseError(
                    ReasonCode.MALFORMED_JSON,
                    f"companyfacts concept {qualified} unit {unit!r} is not "
                    "a JSON array of observations",
                )
            self.emit(f"          {json.dumps(unit, ensure_ascii=False)}: [\n")
            for o_index, observation in enumerate(observations):
                if not isinstance(observation, dict):
                    raise ParseError(
                        ReasonCode.MALFORMED_JSON,
                        f"companyfacts concept {qualified} unit {unit!r} "
                        "contains a non-object observation",
                    )
                fragment = _render_json_value(observation)
                self.emit("            ")
                start = self.pos
                self.emit(fragment)
                end = self.pos
                self.emit(",\n" if o_index < len(observations) - 1 else "\n")
                self._record_observation(
                    qualified, label, unit, section_id, observation, fragment, start, end
                )
            self.emit("          ]")
            self.emit(",\n" if u_index < len(unit_names) - 1 else "\n")
        self.emit("        }")

    def _record_observation(
        self,
        qualified: str,
        label: str | None,
        unit: str,
        section_id: str,
        observation: dict[str, object],
        covered: str,
        start: int,
        end: int,
    ) -> None:
        # The span exists for EVERY observation (it is real document
        # content); a fact is only minted for numeric values.
        span_id = str(uuid.uuid5(ID_NAMESPACE, f"{self._seed}|span|{start}|{end}"))
        self.spans.append(
            SourceSpan(
                id=span_id,
                section_id=section_id,
                start_char=start,
                end_char=end,
                text_hash=text_hash(covered),
                text=covered,
            )
        )
        period_end = _iso_date(observation.get("end"), concept=qualified, field="end")
        period_start: date | None = None
        if observation.get("start") is not None:
            period_start = _iso_date(observation.get("start"), concept=qualified, field="start")
        if "val" not in observation:
            self.diagnostics.append(
                f"skipped observation without 'val' for '{qualified}' at chars {start}-{end}"
            )
            return
        value = observation["val"]
        if isinstance(value, bool) or not isinstance(value, int | Decimal):
            self.diagnostics.append(
                f"skipped non-numeric ({type(value).__name__}) observation "
                f"for '{qualified}' at chars {start}-{end}"
            )
            return
        magnitude = value if isinstance(value, Decimal) else Decimal(value)
        dimensions = {
            key: str(observation[key])
            for key in _PROVENANCE_KEYS
            if observation.get(key) is not None
        }
        self.observations.append(
            CompanyFactsObservation(
                taxonomy=qualified.split(":", 1)[0],
                concept=qualified,
                label=label,
                unit=unit,
                value=magnitude,
                period_start=period_start,
                period_end=period_end,
                dimensions=MappingProxyType(dimensions),
                span_id=span_id,
                start_char=start,
                end_char=end,
            )
        )


def parse_company_facts(
    raw: bytes, *, id_seed: str | None = None, content_hash: str | None = None
) -> ParsedCompanyFacts:
    """Parse companyfacts bytes into canonical text, hierarchy, and spans.

    Mirrors ``parse_filing``'s seeding contract: ``id_seed`` (the pipeline
    passes the document-version id) scopes the deterministic UUIDv5
    section/span identifiers; ``content_hash`` may be passed pre-computed so
    the bytes are hashed exactly once.
    """
    if content_hash is None:
        content_hash, _ = content_address(raw)
    seed = id_seed if id_seed is not None else f"{content_hash}|{COMPANY_FACTS_PARSER_VERSION}"
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(
            ReasonCode.ENCODING_ERROR,
            f"companyfacts payload is not valid UTF-8 (byte offset {exc.start})",
        ) from exc
    try:
        payload = json.loads(decoded, parse_float=Decimal, parse_constant=_reject_non_finite)
    except json.JSONDecodeError as exc:
        raise ParseError(
            ReasonCode.MALFORMED_JSON,
            f"companyfacts payload is not valid JSON (line {exc.lineno} "
            f"column {exc.colno}: {exc.msg})",
        ) from exc
    if not isinstance(payload, dict):
        raise ParseError(
            ReasonCode.MALFORMED_JSON,
            "companyfacts payload is not a JSON object; the source is not a "
            "companyfacts API response",
        )
    if not payload:
        raise ParseError(
            ReasonCode.EMPTY_DOCUMENT,
            "companyfacts payload is an empty JSON object; the source is " "likely truncated",
        )
    builder = _CanonicalBuilder(seed)
    builder.render_document(payload)
    text = builder.text
    root = Section(
        id=builder.root_id,
        parent_id=None,
        heading=ROOT_HEADING,
        heading_path=(ROOT_HEADING,),
        order=0,
        start_char=0,
        end_char=len(text),
    )
    return ParsedCompanyFacts(
        content_hash=content_hash,
        parser_version=COMPANY_FACTS_PARSER_VERSION,
        text=text,
        sections=(root, *builder.sections),
        spans=tuple(builder.spans),
        observations=tuple(builder.observations),
        diagnostics=tuple(builder.diagnostics),
    )


def normalize_company_facts(
    parsed: ParsedCompanyFacts,
    *,
    entity_id: str,
    document_version_id: str,
) -> list[NormalizedFact]:
    """Normalize companyfacts observations into financial-fact/v1 records.

    Restatement isolation (issue #83 ruling): there is deliberately NO
    ``prior_facts`` parameter — companyfacts snapshots never record
    ``restates`` linkage, in either direction. Duplicate handling within the
    snapshot mirrors the filing normalizer: identical fact key + value
    collapses onto the canonical row; conflicting values fail closed.
    """
    canonical: dict[str, NormalizedFact] = {}
    out: list[NormalizedFact] = []
    for observation in parsed.observations:
        if not observation.value.is_finite():
            raise NormalizationError(
                ReasonCode.NONFINITE_FACT_VALUE,
                f"companyfacts fact '{observation.concept}' has non-finite "
                f"value {observation.value}; NaN/Infinity are never storable",
            )
        unit = map_unit(observation.unit)
        if observation.period_start is not None:
            period_type = "duration"
            period_instant: date | None = None
            period_start: date | None = observation.period_start
            period_end: date | None = observation.period_end
        else:
            period_type = "instant"
            period_instant = observation.period_end
            period_start = period_end = None
        key = fact_key(
            observation.concept,
            unit,
            period_type=period_type,
            period_instant=period_instant,
            period_start=period_start,
            period_end=period_end,
            dimensions=observation.dimensions,
        )
        value_text = decimal_str(observation.value)
        duplicate_of: str | None = None
        existing = canonical.get(key)
        if existing is not None:
            if existing.value != value_text:
                raise NormalizationError(
                    ReasonCode.INCONSISTENT_DUPLICATE,
                    f"companyfacts fact '{observation.concept}' ({key}) "
                    f"appears twice with conflicting values {existing.value} "
                    f"(span {existing.source_span_id}) and {value_text} "
                    f"(span {observation.span_id}); the snapshot needs "
                    "manual review",
                )
            duplicate_of = existing.id
        ordinal = len(out)
        normalized = NormalizedFact(
            id=str(uuid.uuid5(ID_NAMESPACE, f"{document_version_id}|fact|{ordinal}|{key}")),
            entity_id=entity_id,
            document_version_id=document_version_id,
            concept=observation.concept,
            label=observation.label,
            value=value_text,
            unit=unit,
            scale=0,
            period_type=period_type,
            period_instant=period_instant,
            period_start=period_start,
            period_end=period_end,
            dimensions=observation.dimensions,
            source_span_id=observation.span_id,
            reported_or_derived="reported",
            confidence=1.0,
            fact_key=key,
            duplicate_of=duplicate_of,
            restates=None,
        )
        if duplicate_of is None:
            canonical[key] = normalized
        out.append(normalized)
    return out


def ingest_company_facts(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    *,
    cik: str,
    raw: bytes,
    fetched_at: datetime,
    source_url: str | None = None,
) -> IngestionOutcome:
    """Store -> parse -> normalize -> persist one companyfacts snapshot.

    Mirrors ``ingest_filing``'s idempotency and quarantine contract exactly
    (claim-upfront ledger, content-keyed job identity, fail-closed
    quarantine) with this channel's parser/normalizer versions, the
    snapshot-scoped accession, and NO restatement linkage.
    """
    cik10 = normalize_cik(cik)
    entity_id = entity_id_for_cik(cik10)
    content_hash, storage_key = content_address(raw)
    accession = company_facts_accession(cik10, fetched_at, content_hash)
    url = source_url if source_url is not None else company_facts_url(cik10)
    key = job_key(
        content_hash,
        COMPANY_FACTS_PARSER_VERSION,
        COMPANY_FACTS_NORMALIZER_VERSION,
        entity_id=entity_id,
        accession=accession,
    )
    document_id = document_id_for_accession(accession)
    version_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://financial-evidence-lab.dev/version|{document_id}|{content_hash}"
            f"|{COMPANY_FACTS_PARSER_VERSION}|{COMPANY_FACTS_NORMALIZER_VERSION}",
        )
    )
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as run_cur:
            claimed = run_cur.execute(
                "INSERT INTO ingestion_runs (job_key, source_hash, parser_version,"
                " normalizer_version, status) VALUES (%s, %s, %s, %s, 'running')"
                " ON CONFLICT (job_key) DO NOTHING RETURNING job_key",
                (key, content_hash, COMPANY_FACTS_PARSER_VERSION, COMPANY_FACTS_NORMALIZER_VERSION),
            ).fetchone()
            if claimed is None:
                existing = run_cur.execute(
                    "SELECT job_key, document_id, document_version_id, status, result"
                    " FROM ingestion_runs WHERE job_key = %s",
                    (key,),
                ).fetchone()
                if existing is None or existing["status"] == "running":
                    raise RuntimeError(f"ingestion run {key} is claimed but has no terminal result")
                return _noop_outcome(key, dict(existing))

        stored: StoredDocument | None = None
        try:
            stored = store_raw_document(
                conn,
                storage,
                entity_id=entity_id,
                accession=accession,
                source_url=url,
                raw=raw,
                published_at=fetched_at,
                form=COMPANY_FACTS_FORM,
                mime_type=COMPANY_FACTS_MIME_TYPE,
                content_hash=content_hash,
                storage_key=storage_key,
            )
            parsed = parse_company_facts(raw, id_seed=version_id, content_hash=content_hash)
            facts = normalize_company_facts(
                parsed, entity_id=entity_id, document_version_id=version_id
            )
        except IngestError as exc:
            # The hash-suffixed accession makes DIVERGENT_ACCESSION_CONTENT
            # unreachable short of an 8-hex-char prefix collision; the
            # fail-closed quarantine path is kept for exactly that case.
            quarantine_document_id = stored.document_id if stored is not None else None
            _record_quarantine(
                conn,
                key=key,
                accession=accession,
                source_url=url,
                content_hash=content_hash,
                document_id=quarantine_document_id,
                reason_code=exc.reason_code,
                diagnostic=exc.diagnostic,
            )
            return IngestionOutcome(
                status="quarantined",
                job_key=key,
                document_id=quarantine_document_id,
                document_version_id=None,
                reason_code=exc.reason_code,
                diagnostic=exc.diagnostic,
            )

        text_key = canonical_text_address(parsed.text)
        storage.put(text_key, parsed.text.encode())
        conn.execute(
            "INSERT INTO document_versions"
            " (id, document_id, parser_version, normalizer_version, status,"
            "  canonical_text_key)"
            " VALUES (%s, %s, %s, %s, 'parsed', %s)",
            (
                version_id,
                stored.document_id,
                COMPANY_FACTS_PARSER_VERSION,
                COMPANY_FACTS_NORMALIZER_VERSION,
                text_key,
            ),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO sections (id, document_version_id, parent_id, heading,"
                " heading_path, ord, start_char, end_char)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        section.id,
                        version_id,
                        section.parent_id,
                        section.heading,
                        list(section.heading_path),
                        section.order,
                        section.start_char,
                        section.end_char,
                    )
                    for section in parsed.sections
                ],
            )
            cur.executemany(
                "INSERT INTO source_spans (id, document_version_id, section_id,"
                " start_char, end_char, text_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (
                        span.id,
                        version_id,
                        span.section_id,
                        span.start_char,
                        span.end_char,
                        span.text_hash,
                    )
                    for span in parsed.spans
                ],
            )
            cur.executemany(
                """
                INSERT INTO financial_facts
                    (id, entity_id, document_version_id, concept, label, value,
                     unit, scale, period_type, period_instant, period_start,
                     period_end, dimensions, source_span_id, reported_or_derived,
                     confidence, duplicate_of, restates, fact_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                """,
                [
                    (
                        fact.id,
                        fact.entity_id,
                        fact.document_version_id,
                        fact.concept,
                        fact.label,
                        fact.value,
                        fact.unit,
                        fact.scale,
                        fact.period_type,
                        fact.period_instant,
                        fact.period_start,
                        fact.period_end,
                        json.dumps(dict(fact.dimensions)),
                        fact.source_span_id,
                        fact.reported_or_derived,
                        fact.confidence,
                        fact.duplicate_of,
                        fact.restates,
                        fact.fact_key,
                    )
                    for fact in facts
                ],
            )
        result = {
            "sections": len(parsed.sections),
            "spans": len(parsed.spans),
            "tables": 0,
            "facts": len(facts),
        }
        conn.execute(
            "UPDATE ingestion_runs SET status = 'succeeded', document_id = %s,"
            " document_version_id = %s, result = %s WHERE job_key = %s",
            (stored.document_id, version_id, json.dumps(result), key),
        )
        return IngestionOutcome(
            status="succeeded",
            job_key=key,
            document_id=stored.document_id,
            document_version_id=version_id,
            sections=len(parsed.sections),
            spans=len(parsed.spans),
            tables=0,
            facts=len(facts),
        )


def handle_sec_company_facts(
    conn: psycopg.Connection[Any],
    storage: StorageProvider,
    sec: CompanyFactsSecClient,
    payload: dict[str, Any],
) -> IngestionOutcome:
    """Handle one ``sec_company_facts`` job: fetch the snapshot and ingest it."""
    cik = str(payload.get("cik") or "")
    if not cik:
        raise ValueError(f"sec_company_facts payload is missing cik: {payload!r}")
    fetched = sec.company_facts(cik)
    raw = canonical_company_facts_bytes(fetched)
    return ingest_company_facts(
        conn,
        storage,
        cik=cik,
        raw=raw,
        fetched_at=datetime.now(UTC),
    )


def enqueue_company_facts(
    conn: psycopg.Connection[Any],
    *,
    cik: str,
    job_queue: str = "ingestion",
    snapshot_day: date | None = None,
    priority: int = 5,
) -> str:
    """Enqueue one idempotent companyfacts snapshot job for an issuer.

    The idempotency key is namespaced to the kind and scoped to the CIK and
    UTC day (``sec-companyfacts|<cik10>|<UTC date>``): re-enqueueing the same
    issuer on the same day replays the existing job instead of duplicating
    work; the next day mints a fresh snapshot job.
    """
    cik10 = normalize_cik(cik)
    day = snapshot_day if snapshot_day is not None else datetime.now(UTC).date()
    return queue.enqueue(
        conn,
        kind=JOB_KIND_SEC_COMPANY_FACTS,
        payload={"cik": cik10},
        queue=job_queue,
        priority=priority,
        idempotency_key=f"sec-companyfacts|{cik10}|{day.isoformat()}",
    )
