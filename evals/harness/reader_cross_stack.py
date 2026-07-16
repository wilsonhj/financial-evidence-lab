"""ADR-0005 reader cross-stack verification harness (issue #96).

Mock-first: committed fixtures under ``evals/datasets/reader-cross-stack/``
drive pure Python checks that mirror the production web reader's citation
integrity and HttpEvidenceSource error policy. Optional stack path hits the
real FastAPI composite reader when ``TEST_DATABASE_URL`` is configured.

This module must not import or patch ``apps/web``; web semantics that matter
for acceptance are re-expressed here so evals stay path-isolated.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlencode

DATASET_DIR = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "reader-cross-stack"
FIXTURES_DIR = DATASET_DIR / "fixtures"

EvidenceFailureKind = Literal[
    "authentication", "forbidden", "conflict", "invalid_scope", "unavailable", "not_found"
]


class ReaderCrossStackError(RuntimeError):
    """Harness-level failure (fixture load, contract invariant, policy)."""


@dataclass(frozen=True)
class CitationIntegrityFailure:
    span_id: str
    section_id: str
    reason: str


@dataclass(frozen=True)
class SpanVerificationResult:
    verified: list[dict[str, Any]]
    failures: list[CitationIntegrityFailure]


@dataclass(frozen=True)
class EvidenceApiFailure(Exception):
    status: int
    kind: EvidenceFailureKind
    code: str | None
    path: str

    def __str__(self) -> str:
        return f"EvidenceApiFailure({self.kind}, HTTP {self.status}, {self.path})"


def load_json(name: str) -> Any:
    path = FIXTURES_DIR / name
    if not path.is_file():
        raise ReaderCrossStackError(f"missing fixture {path}")
    return json.loads(path.read_text())


def load_scenarios() -> dict[str, Any]:
    return json.loads((DATASET_DIR / "scenarios.json").read_text())


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def section_range_consistent(section: dict[str, Any]) -> bool:
    start = section.get("start_char")
    end = section.get("end_char")
    content = section.get("content")
    return (
        isinstance(start, int)
        and isinstance(end, int)
        and isinstance(content, str)
        and start >= 0
        and end >= start
        and len(content) == end - start
    )


def derive_local_anchor(
    section: dict[str, Any], span: dict[str, Any]
) -> tuple[bool, int, int, str | None]:
    if not section_range_consistent(section):
        return False, 0, 0, "section_range_mismatch"
    start = span.get("start_char")
    end = span.get("end_char")
    if not (
        isinstance(start, int)
        and isinstance(end, int)
        and start >= section["start_char"]
        and end > start
        and end <= section["end_char"]
    ):
        return False, 0, 0, "offsets_out_of_range"
    return True, start - section["start_char"], end - section["start_char"], None


def verify_span_integrity(
    sections: list[dict[str, Any]], spans: list[dict[str, Any]]
) -> SpanVerificationResult:
    """Python port of apps/web citation-integrity fail-closed checks."""
    by_id = {section["id"]: section for section in sections}
    verified: list[dict[str, Any]] = []
    failures: list[CitationIntegrityFailure] = []
    for record in spans:
        span = record["span"]
        section_id = span["section_id"]
        section = by_id.get(section_id)
        if section is None:
            failures.append(CitationIntegrityFailure(record["id"], section_id, "unknown_section"))
            continue
        ok, local_start, local_end, reason = derive_local_anchor(section, span)
        if not ok:
            failures.append(
                CitationIntegrityFailure(record["id"], section_id, reason or "integrity_failed")
            )
            continue
        cited = section["content"][local_start:local_end]
        if f"sha256:{sha256_hex(cited)}" != span["text_hash"]:
            failures.append(
                CitationIntegrityFailure(record["id"], section_id, "text_hash_mismatch")
            )
            continue
        verified.append({**record, "verified_quote": cited})
    return SpanVerificationResult(verified=verified, failures=failures)


def assert_document_id_differs_from_version(body: dict[str, Any]) -> None:
    document = body["document"]
    doc_id = document["meta"]["id"]
    version_id = document["document_version_id"]
    if doc_id == version_id:
        raise ReaderCrossStackError("document id must differ from selected version id")
    for sibling in body.get("siblings", []):
        if sibling["meta"]["id"] == sibling["document_version_id"]:
            raise ReaderCrossStackError("sibling document id equals version id")


def assert_selection_policy(body: dict[str, Any]) -> None:
    pin = body.get("corpus_version_id")
    policy = body.get("selection_policy")
    if pin is None:
        if policy != "latest_parsed":
            raise ReaderCrossStackError("unpinned response must use latest_parsed")
    else:
        if policy != "corpus_pinned":
            raise ReaderCrossStackError("pinned response must use corpus_pinned")
        if pin != body["corpus_version_id"]:
            raise ReaderCrossStackError("corpus pin echo mismatch")


def assert_cutoff_scope(body: dict[str, Any]) -> None:
    cutoff = datetime.fromisoformat(body["as_of"].replace("Z", "+00:00"))
    published = datetime.fromisoformat(
        body["document"]["meta"]["published_at"].replace("Z", "+00:00")
    )
    if published > cutoff:
        raise ReaderCrossStackError("target published_at exceeds effective as_of")
    for sibling in body.get("siblings", []):
        sib_pub = datetime.fromisoformat(sibling["meta"]["published_at"].replace("Z", "+00:00"))
        if sib_pub > cutoff:
            raise ReaderCrossStackError("sibling published_at exceeds effective as_of")


def assert_facts_resolve_same_version_spans(body: dict[str, Any]) -> None:
    blocks = [body["document"], *body.get("siblings", [])]
    all_fact_ids = {item["id"] for block in blocks for item in block["facts"]}
    for block in blocks:
        version_id = block["document_version_id"]
        span_ids = {item["id"] for item in block["spans"]}
        for item in block["facts"]:
            if item["document_version_id"] != version_id:
                raise ReaderCrossStackError("fact crosses selected document version")
            source = item["fact"]["source_span_id"]
            if source not in span_ids:
                raise ReaderCrossStackError("fact.source_span_id does not resolve in block")
            for link in ("duplicate_of", "restates"):
                target = item.get(link)
                if target is not None and target not in all_fact_ids:
                    raise ReaderCrossStackError(f"{link} does not resolve in response")


def non_first_section_verified_quote(body: dict[str, Any]) -> str:
    """Return the hash-verified quote for a span anchored past the first section."""
    sections = sorted(body["document"]["sections"], key=lambda s: s["ord"])
    if len(sections) < 2:
        raise ReaderCrossStackError("fixture must include a non-first section")
    first_end = sections[0]["end_char"]
    result = verify_span_integrity(body["document"]["sections"], body["document"]["spans"])
    for record in result.verified:
        if record["span"]["start_char"] >= first_end:
            quote = record["verified_quote"]
            if not quote:
                raise ReaderCrossStackError("verified quote is empty")
            return quote
    raise ReaderCrossStackError("no verified non-first-section citation found")


def classify_http_failure(status: int) -> EvidenceFailureKind:
    """Mirror HttpEvidenceSource failureKind — 401/403/5xx are never not_found."""
    if status == 401:
        return "authentication"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 422:
        return "invalid_scope"
    return "unavailable"


def assert_auth_errors_are_not_404(envelopes: dict[str, Any]) -> list[EvidenceApiFailure]:
    failures: list[EvidenceApiFailure] = []
    mapping = {
        "unauthenticated": 401,
        "forbidden": 403,
        "integrity": 500,
    }
    for key, status in mapping.items():
        envelope = envelopes[key]
        code = envelope["error"]["code"]
        kind = classify_http_failure(status)
        if kind == "not_found" or status == 404:
            raise ReaderCrossStackError(f"{key} incorrectly classified as 404")
        if code == "NOT_FOUND":
            raise ReaderCrossStackError(f"{key} envelope must not use NOT_FOUND")
        failures.append(
            EvidenceApiFailure(status=status, kind=kind, code=code, path="/v1/documents/x/reader")
        )
    not_found = envelopes["not_found"]
    if not_found["error"]["code"] != "NOT_FOUND":
        raise ReaderCrossStackError("missing-document envelope must be NOT_FOUND")
    return failures


@dataclass(frozen=True)
class AmendmentLink:
    original_id: str
    amendment_id: str


AmendmentStatusKind = Literal["original", "superseded", "amendment"]


@dataclass(frozen=True)
class AmendmentStatus:
    kind: AmendmentStatusKind
    by_document_id: str | None = None
    amends_document_id: str | None = None


def _is_amendment_form(form: str | None) -> bool:
    return isinstance(form, str) and form.endswith("/A")


def _base_form(form: str | None) -> str | None:
    if not form:
        return None
    return form[:-2] if _is_amendment_form(form) else form


def _published_epoch(doc: dict[str, Any]) -> float:
    return datetime.fromisoformat(doc["published_at"].replace("Z", "+00:00")).timestamp()


def _periods_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if not a.get("period_start") or not a.get("period_end"):
        return False
    if not b.get("period_start") or not b.get("period_end"):
        return False
    return a["period_start"] == b["period_start"] and a["period_end"] == b["period_end"]


def link_amendments(documents: list[dict[str, Any]]) -> list[AmendmentLink]:
    """Port of apps/web linkAmendments — terminal chain uses latest published."""
    links: list[AmendmentLink] = []
    for amendment in documents:
        if not _is_amendment_form(amendment.get("form")):
            continue
        amendment_epoch = _published_epoch(amendment)
        candidates = [
            doc
            for doc in documents
            if doc["id"] != amendment["id"]
            and doc["entity_id"] == amendment["entity_id"]
            and _base_form(doc.get("form")) == _base_form(amendment.get("form"))
            and _periods_match(doc, amendment)
            and (
                _published_epoch(doc) < amendment_epoch
                if _is_amendment_form(doc.get("form"))
                else _published_epoch(doc) <= amendment_epoch
            )
        ]
        candidates.sort(key=lambda doc: (_published_epoch(doc), doc["id"]))
        if candidates:
            links.append(
                AmendmentLink(original_id=candidates[-1]["id"], amendment_id=amendment["id"])
            )
    return links


def amendment_status_for(document_id: str, links: list[AmendmentLink]) -> AmendmentStatus:
    superseded_by = {link.original_id: link.amendment_id for link in links}
    if document_id in superseded_by:
        current = superseded_by[document_id]
        visited = {document_id}
        while current in superseded_by and current not in visited:
            visited.add(current)
            current = superseded_by[current]
        return AmendmentStatus(kind="superseded", by_document_id=current)
    for link in links:
        if link.amendment_id == document_id:
            return AmendmentStatus(kind="amendment", amends_document_id=link.original_id)
    return AmendmentStatus(kind="original")


def terminal_authoritative_id(documents: list[dict[str, Any]]) -> str:
    links = link_amendments(documents)
    originals = [doc for doc in documents if not _is_amendment_form(doc.get("form"))]
    if not originals:
        raise ReaderCrossStackError("amendment chain fixture missing original filing")
    status = amendment_status_for(originals[0]["id"], links)
    if status.kind != "superseded" or not status.by_document_id:
        raise ReaderCrossStackError("original must resolve to a terminal amendment")
    return status.by_document_id


class MockHttpEvidenceTransport:
    """Minimal HttpEvidenceSource stand-in for mock-first cross-stack checks.

    HTTP mode never falls back to fixtures: callers must supply an explicit
    route table. Missing routes and error statuses surface as failures; they
    do not silently return ``latest_parsed_ok.json``.
    """

    def __init__(self, routes: dict[tuple[str, str], tuple[int, Any]]) -> None:
        # key: (method, path_with_query) -> (status, body)
        self._routes = routes
        self.fixture_fallback_attempted = False

    def get_reader(
        self,
        document_id: str,
        *,
        as_of: str | None = None,
        corpus_version_id: str | None = None,
    ) -> dict[str, Any] | None:
        query: dict[str, str] = {}
        if as_of:
            query["as_of"] = as_of
        if corpus_version_id:
            query["corpus_version_id"] = corpus_version_id
        suffix = f"?{urlencode(query)}" if query else ""
        path = f"/v1/documents/{document_id}/reader{suffix}"
        key = ("GET", path)
        if key not in self._routes:
            # Explicitly refuse fixture fallback when the stack route is absent.
            self.fixture_fallback_attempted = False
            raise EvidenceApiFailure(status=0, kind="unavailable", code=None, path=path)
        status, body = self._routes[key]
        if status == 404:
            return None
        if status != 200:
            kind = classify_http_failure(status)
            code = None
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                code = body["error"].get("code")
            raise EvidenceApiFailure(status=status, kind=kind, code=code, path=path)
        if not isinstance(body, dict):
            raise ReaderCrossStackError(
                f"reader 200 body must be an object, got {type(body).__name__}"
            )
        return body


def assert_http_mode_no_fixture_fallback() -> None:
    """When the stack is available, HTTP mode must not substitute fixtures."""
    ok = load_json("latest_parsed_ok.json")
    doc_id = ok["document"]["meta"]["id"]
    path = f"/v1/documents/{doc_id}/reader"
    transport = MockHttpEvidenceTransport(
        {
            ("GET", path): (200, ok),
            ("GET", f"/v1/documents/{doc_id}/reader?as_of=2026-07-01T00%3A00%3A00Z"): (
                401,
                load_json("error_envelopes.json")["unauthenticated"],
            ),
        }
    )
    first = transport.get_reader(doc_id)
    second = transport.get_reader(doc_id)
    if first != second:
        raise ReaderCrossStackError("repeated mock HTTP reads must be identical")
    assert_document_id_differs_from_version(first)  # type: ignore[arg-type]

    try:
        transport.get_reader(doc_id, as_of="2026-07-01T00:00:00Z")
    except EvidenceApiFailure as exc:
        if exc.status == 404 or exc.kind == "not_found":
            raise ReaderCrossStackError("401 must not collapse to 404") from exc
        if exc.kind != "authentication":
            raise ReaderCrossStackError(f"expected authentication, got {exc.kind}") from exc
    else:
        raise ReaderCrossStackError("expected authentication failure")

    missing = MockHttpEvidenceTransport({})
    try:
        missing.get_reader(doc_id)
    except EvidenceApiFailure:
        if missing.fixture_fallback_attempted:
            raise ReaderCrossStackError("HTTP mode attempted fixture fallback") from None
    else:
        raise ReaderCrossStackError("missing stack route must fail closed")


def assert_reader_response_invariants(body: dict[str, Any]) -> None:
    assert_document_id_differs_from_version(body)
    assert_selection_policy(body)
    assert_cutoff_scope(body)
    assert_facts_resolve_same_version_spans(body)
