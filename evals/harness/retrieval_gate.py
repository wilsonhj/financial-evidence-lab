"""Executable retrieval release gate over the benchmark seed (issue #201).

Builds a small synthetic corpus + index version whose documents are minted
directly from the benchmark seed's own golden evidence quotes
(``evals/datasets/benchmark-seed/questions.jsonl``), runs every seed question
through the real ``fel_retrieval`` pipeline (planner -> lanes -> fusion, mock
embedding provider only), grades the run with
``fel_retrieval_evals.metrics.build_gate_report`` and writes a deterministic
JSON report.

Why a *synthesized* corpus rather than the live SEC corpus: the seed's
evidence cites real EDGAR filings (issue #177 tracks a credentialed live
corpus/provider); until that lands there is nothing in Postgres for those
accessions to resolve against. This harness instead builds one small
document per cited accession whose text *is* the golden quote(s) — the same
literal strings ``fel_retrieval_evals.compile`` resolves offsets against — so
Recall@10 and the cutoff guard are graded against real, code-run retrieval
rather than fabricated. See "Gates computed vs. not evaluable" below.

Gates computed vs. not evaluable
---------------------------------
The pipeline exercised here is retrieval-only (planner + lanes + fusion); it
never runs claim/citation generation (that is ``apps/api``'s generation
stage, out of scope for this package). Of the five smoke gates in
``fel_retrieval_evals.metrics.SMOKE_THRESHOLDS``:

* ``recall_at_10`` — COMPUTED. Gold ids are the deterministic item ids of the
  passages built from each answerable question's evidence quotes (see
  ``fel_retrieval.ids.item_id``); unanswerable (negative) questions
  vacuously pass (no gold to find).
* ``temporal_validity`` — COMPUTED. True when every fused candidate for a
  question carries ``published_at <= as_of`` — the same cutoff guard
  ``fel_retrieval.lanes`` enforces in SQL, checked here from the pipeline's
  actual output rather than assumed.
* ``numeric_accuracy``, ``entailment_precision``, ``citation_completeness``
  — NOT EVALUABLE. Each requires a generated answer with typed numeric
  claims and citations; retrieval alone produces neither. Reported under
  the report's ``not_evaluable`` block with a zero support count rather
  than a fabricated pass, and excluded from the pass/fail gate and exit
  code entirely (never "fail closed" on a metric that was never measured
  *or run*).

Determinism: the corpus/index identity is derived entirely from the content
of the questions file (a UUIDv5 over its sha256), so two runs against an
unchanged seed reuse the same corpus/index rows (``build_index`` resumes a
``ready``/``superseded`` version untouched) and produce a byte-identical
graded report section.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fel_retrieval import (
    LANE_DENSE,
    LANE_FACTS,
    LANE_LEXICAL,
    LANE_TABLES,
    LaneCandidate,
    LaneQuery,
    QueryRequest,
    build_index,
    content_sha256,
    dense_lane,
    facts_lane,
    fuse,
    item_id,
    lexical_lane,
    make_index_version_spec,
    plan_query,
    publish_index_version,
    source_anchor,
    tables_lane,
)
from fel_retrieval_evals.compile import CompilationError, compile_manifest, load_seed
from fel_retrieval_evals.corpus import JsonCorpus
from fel_retrieval_evals.metrics import (
    SMOKE_THRESHOLDS,
    QuestionOutcome,
    aggregate_metrics,
    build_gate_report,
    metric_supports,
    question_recall_at_k,
)
from fel_retrieval_evals.models import ManifestEntry

try:  # driver is a dev dependency; the DB-backed path requires it
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - psycopg is in requirements-dev
    psycopg = None  # type: ignore[assignment]

SCHEMA_VERSION = "retrieval-gate-report/v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = REPO_ROOT / "evals" / "datasets" / "benchmark-seed" / "questions.jsonl"

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://financial-evidence-lab.dev/retrieval-gate")

_PROVIDER_NAME = "mock"
_MODEL_NAME = "mock-embed-retrieval-gate-v1"

_LANE_FNS: dict[str, Any] = {
    LANE_DENSE: dense_lane,
    LANE_LEXICAL: lexical_lane,
    LANE_FACTS: facts_lane,
    LANE_TABLES: tables_lane,
}

# Gates this retrieval-only pipeline can actually measure (see module
# docstring). The other two SMOKE_THRESHOLDS keys are reported separately
# under ``not_evaluable`` and never affect the exit code.
_COMPUTABLE_THRESHOLDS: dict[str, Decimal] = {
    "temporal_validity": SMOKE_THRESHOLDS["temporal_validity"],
    "recall_at_10": SMOKE_THRESHOLDS["recall_at_10"],
}
_NOT_EVALUABLE_METRICS: tuple[str, ...] = (
    "numeric_accuracy",
    "entailment_precision",
    "citation_completeness",
)
_NOT_EVALUABLE_REASON = (
    "requires a generated answer's typed claims and citations; this gate runs "
    "planner + lanes + fusion only (no generation stage), so no answer, claim, "
    "or citation ever exists to grade -- reported here rather than fabricated "
    "or silently passed"
)


def _parse_dt(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus_version_id(questions_sha256: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"corpus:{questions_sha256}"))


def _issuer_entity_id(issuer: Mapping[str, Any]) -> str:
    key = str(issuer.get("cik") or issuer.get("ticker") or "unknown-issuer")
    return str(uuid.uuid5(_NAMESPACE, f"entity:{key}"))


@dataclass(frozen=True)
class _AccessionPlan:
    """Resolved acceptance timestamp + citing issuer for one accession."""

    accession: str
    published_at: datetime
    entity_id: str


def _accession_plans(records: Sequence[dict[str, Any]]) -> dict[str, _AccessionPlan]:
    """Pick one deterministic ``published_at``/``entity_id`` per accession.

    ``published_at`` must satisfy every record that cites the accession
    (evidence or ``documents_reviewed``, which must stay <= that record's
    ``as_of``) *and* every record that lists it as a ``future_revisions``
    trap (which must stay > that record's ``as_of``). The seed's traps only
    ever reference an accession as a future revision for an *earlier*
    ``as_of`` than any record that later cites it, so a single timestamp
    strictly between the two satisfies both; a same-day match against a
    provisional midnight ``as_of`` is nudged back a day (compile.py's
    provisional-midnight rule).
    """
    cited_as_of: dict[str, list[datetime]] = {}
    future_as_of: dict[str, list[datetime]] = {}
    entity_of: dict[str, str] = {}
    for record in records:
        issuer = record.get("issuer", {})
        cited = {e["accession"] for e in record["evidence"]} | set(record["documents_reviewed"])
        for accession in cited:
            cited_as_of.setdefault(accession, []).append(_parse_dt(record["as_of"]))
            entity_of.setdefault(accession, _issuer_entity_id(issuer))
        for accession in record.get("future_revisions", []):
            future_as_of.setdefault(accession, []).append(_parse_dt(record["as_of"]))
            entity_of.setdefault(accession, _issuer_entity_id(issuer))

    plans: dict[str, _AccessionPlan] = {}
    for accession in set(cited_as_of) | set(future_as_of):
        cited_list = cited_as_of.get(accession, [])
        future_list = future_as_of.get(accession, [])
        cap = min(cited_list) - timedelta(days=1) if cited_list else None
        base = max(future_list) + timedelta(hours=12) if future_list else None
        if base is not None and cap is not None:
            candidate = base if base < cap else cap - timedelta(hours=1)
        elif base is not None:
            candidate = base
        elif cap is not None:
            candidate = cap
        else:  # pragma: no cover - accession came from one of the two dicts
            raise GateBuildError(f"accession {accession!r} has neither a cited nor future as_of")
        for as_of in cited_list:
            if as_of.time() == dtime(0, 0, 0) and candidate.date() == as_of.date():
                candidate = candidate - timedelta(days=1)
        plans[accession] = _AccessionPlan(
            accession=accession, published_at=candidate, entity_id=entity_of[accession]
        )
    return plans


def _build_json_corpus(
    records: Sequence[dict[str, Any]], plans: Mapping[str, _AccessionPlan]
) -> tuple[JsonCorpus, dict[tuple[str, str, str], str]]:
    """A ``fel_retrieval_evals`` ``Corpus`` fixture over the resolved plans.

    Every evidence quote becomes its own span (stable UUIDv5 id); returns the
    corpus plus the ``(accession, section, quote) -> span_id`` map so the
    Postgres builder below can mint identical span ids.
    """
    spans_by_accession: dict[str, list[dict[str, str]]] = {accession: [] for accession in plans}
    span_ids: dict[tuple[str, str, str], str] = {}
    for record in records:
        for evidence in record["evidence"]:
            key = (evidence["accession"], evidence["section"], evidence["quote"])
            if key in span_ids:
                continue
            span_id = str(uuid.uuid5(_NAMESPACE, f"span:{'|'.join(key)}"))
            span_ids[key] = span_id
            spans_by_accession[evidence["accession"]].append(
                {"section": evidence["section"], "span_id": span_id, "text": evidence["quote"]}
            )
    data: dict[str, dict[str, object]] = {
        accession: {
            "acceptance_timestamp": plan.published_at.isoformat(),
            "spans": spans_by_accession[accession],
        }
        for accession, plan in plans.items()
    }
    return JsonCorpus(data), span_ids


def _accession_documents(
    records: Sequence[dict[str, Any]],
    plans: Mapping[str, _AccessionPlan],
    span_ids: Mapping[tuple[str, str, str], str],
) -> dict[str, dict[str, Any]]:
    """One retrieval-package ``corpus`` dict per accession that has evidence quotes.

    Shape matches what ``fel_retrieval.build_items`` expects (see
    ``packages/retrieval/tests/conftest.py``'s ``_seed_document``): a single
    section holding one source span per distinct quote cited from that
    accession. Accessions that are only ``documents_reviewed`` (no quotes)
    are not built here -- they exist solely in the JSON corpus above so
    ``compile_manifest``'s temporal check can resolve their timestamp.
    """
    quotes_by_accession: dict[str, list[tuple[str, str]]] = {}
    forms_by_accession: dict[str, str] = {}
    for record in records:
        for evidence in record["evidence"]:
            accession = evidence["accession"]
            key = (evidence["section"], evidence["quote"])
            bucket = quotes_by_accession.setdefault(accession, [])
            if key not in bucket:
                bucket.append(key)
            forms_by_accession.setdefault(accession, str(evidence.get("form", "")))

    documents: dict[str, dict[str, Any]] = {}
    for accession, quotes in quotes_by_accession.items():
        plan = plans[accession]
        document_id = str(uuid.uuid5(_NAMESPACE, f"document:{accession}"))
        document_version_id = str(uuid.uuid5(_NAMESPACE, f"document-version:{accession}"))
        section_id = str(uuid.uuid5(_NAMESPACE, f"section:{accession}"))
        heading_path = ["EVIDENCE"]
        canonical_parts: list[str] = []
        spans: list[dict[str, Any]] = []
        offset = 0
        for section, quote in quotes:
            start = offset
            end = start + len(quote)
            spans.append(
                {
                    "id": span_ids[(accession, section, quote)],
                    "section_id": section_id,
                    "start_char": start,
                    "end_char": end,
                    "text": quote,
                    "text_hash": content_sha256(quote),
                    "heading_path": heading_path,
                }
            )
            canonical_parts.append(quote)
            offset = end + 1
        documents[accession] = {
            "entity_id": plan.entity_id,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "form": forms_by_accession.get(accession) or None,
            "canonical_text": "\n".join(canonical_parts),
            "source_spans": spans,
            "financial_facts": [],
            "tables": [],
            "_section_id": section_id,
            "_heading_path": heading_path,
            "_published_at": plan.published_at,
        }
    return documents


def _insert_document(conn: Any, accession: str, doc: dict[str, Any]) -> None:
    """Idempotently insert one accession's document + spans (ON CONFLICT DO NOTHING).

    Mirrors ``packages/retrieval/tests/conftest.py``'s ``_seed_document``
    shape, but with deterministic ids (this corpus is reused across runs,
    not re-randomized per test).
    """
    conn.execute(
        "INSERT INTO documents (id, entity_id, accession, source_url, content_hash, "
        "storage_key, published_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (
            doc["document_id"],
            doc["entity_id"],
            accession,
            f"https://synthetic.invalid/retrieval-gate/{accession}",
            content_sha256(doc["canonical_text"]),
            f"retrieval-gate/{doc['document_id']}",
            doc["_published_at"],
        ),
    )
    conn.execute(
        "INSERT INTO document_versions (id, document_id, parser_version, "
        "normalizer_version, canonical_text_key) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (
            doc["document_version_id"],
            doc["document_id"],
            "retrieval-gate/1",
            "retrieval-gate/1",
            f"text/sha256/{doc['document_id']}",
        ),
    )
    conn.execute(
        "INSERT INTO sections (id, document_version_id, heading, heading_path, ord, "
        "start_char, end_char) VALUES (%s, %s, %s, %s, 0, 0, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (
            doc["_section_id"],
            doc["document_version_id"],
            "EVIDENCE",
            doc["_heading_path"],
            len(doc["canonical_text"]),
        ),
    )
    for span in doc["source_spans"]:
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (
                span["id"],
                doc["document_version_id"],
                span["section_id"],
                span["start_char"],
                span["end_char"],
                span["text_hash"],
            ),
        )


def ensure_retrieval_gate_database(base_url: str) -> str:
    """Create/migrate a ``<db>_retrieval`` sibling, same pattern as the
    retrieval package's own integration fixtures (delete-immutable shared
    tables need isolation from the workers/ingestion suites' cleanup)."""
    from urllib.parse import urlunsplit

    parsed = urlsplit(base_url)
    retrieval_db = parsed.path.lstrip("/") + "_retrieval"
    retrieval_url = urlunsplit(parsed._replace(path="/" + retrieval_db))

    if psycopg is None:  # pragma: no cover - guarded by main() before this is called
        raise GateBuildError("psycopg is not installed (see requirements-dev.txt)")
    with psycopg.connect(base_url, autocommit=True) as conn:
        try:
            conn.execute(f'CREATE DATABASE "{retrieval_db}"')  # noqa: S608 - derived name
        except psycopg.errors.DuplicateDatabase:
            pass

    migrations = sorted((REPO_ROOT / "db" / "migrations").glob("*.sql"))
    with psycopg.connect(retrieval_url, autocommit=True) as conn:
        marker = conn.execute("SELECT to_regclass('public.retrieval_index_versions')").fetchone()
        if marker is None or marker[0] is None:
            for path in migrations:
                conn.execute(path.read_text())
    return retrieval_url


class GateBuildError(RuntimeError):
    """The synthetic corpus/index could not be built or resolved."""


@dataclass(frozen=True)
class BuiltCorpus:
    corpus_version_id: str
    index_version_id: str
    manifest_entries: tuple[ManifestEntry, ...]
    reused: bool
    item_count: int


def build_and_index_corpus(
    conn: Any, records: Sequence[dict[str, Any]], *, questions_sha256: str
) -> BuiltCorpus:
    """Build (or reuse) the synthetic corpus + index version over ``records``."""
    plans = _accession_plans(records)
    json_corpus, span_ids = _build_json_corpus(records, plans)
    corpus_version_id = _corpus_version_id(questions_sha256)

    try:
        manifest = compile_manifest(
            records, corpus=json_corpus, corpus_version_id=corpus_version_id
        )
    except CompilationError as exc:
        raise GateBuildError(f"synthetic corpus fixture failed to resolve: {exc}") from exc

    documents = _accession_documents(records, plans, span_ids)

    from fel_providers import MockEmbeddingProvider

    spec = make_index_version_spec(
        corpus_version_id=corpus_version_id,
        embedding_provider=_PROVIDER_NAME,
        embedding_model=_MODEL_NAME,
    )

    conn.execute(
        "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'draft') "
        "ON CONFLICT (id) DO NOTHING",
        (corpus_version_id, f"retrieval-gate-{corpus_version_id[:8]}"),
    )

    last_status = "ready"
    for accession, doc in sorted(documents.items()):
        _insert_document(conn, accession, doc)
        conn.execute(
            "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (corpus_version_id, doc["document_version_id"]),
        )
        outcome = build_index(
            conn,
            spec=spec,
            corpus={k: v for k, v in doc.items() if not k.startswith("_")},
            provider=MockEmbeddingProvider(512),
        )
        last_status = outcome.status

    reused = last_status in ("ready", "superseded")
    if not reused:
        publish_index_version(conn, spec.id, activate=False)

    item_count = conn.execute(
        "SELECT count(id) FROM retrieval_items WHERE index_version_id = %s", (spec.id,)
    ).fetchone()
    return BuiltCorpus(
        corpus_version_id=corpus_version_id,
        index_version_id=spec.id,
        manifest_entries=manifest.entries,
        reused=reused,
        item_count=int(item_count[0]) if item_count else 0,
    )


@dataclass(frozen=True)
class QuestionResult:
    outcome: QuestionOutcome | None
    diagnostic: dict[str, Any]


def run_question(
    conn: Any,
    entry: ManifestEntry,
    *,
    index_version_id: str,
    corpus_version_id: str,
) -> QuestionResult:
    """Run one manifest entry through planner -> lanes -> fusion; grade it."""
    from fel_providers import MockEmbeddingProvider

    gold_ids = sorted(
        {
            item_id(
                index_version_id,
                "passage",
                source_anchor("passage", source_span_id=e.span_id),
                content_sha256(e.quote),
            )
            for e in entry.evidence
            if e.span_id is not None
        }
    )
    if entry.answerable and entry.evidence and not gold_ids:
        return QuestionResult(
            outcome=None,
            diagnostic={
                "id": entry.id,
                "excluded_reason": "evidence unresolved in synthetic corpus",
            },
        )

    entity_id = _issuer_entity_id(entry.issuer)
    request = QueryRequest(question=entry.question)
    plan = plan_query(
        request,
        index_version_id=index_version_id,
        corpus_version_id=corpus_version_id,
        entity_ids=[entity_id],
        effective_as_of=entry.as_of,
    )

    provider = MockEmbeddingProvider(512)
    query_vector = provider.embed([entry.question])[0]
    as_of = _parse_dt(entry.as_of)
    lane_query = LaneQuery(
        index_version_id=plan.index_version_id,
        as_of=as_of,
        query_text=entry.question,
        query_vector=query_vector,
        corpus_version_id=plan.corpus_version_id,
        top_k=plan.budgets.lane_top_k,
    )
    lane_results: dict[str, list[LaneCandidate]] = {
        lane: _LANE_FNS[lane](conn, lane_query) for lane in plan.lanes
    }
    fusion = fuse(lane_results, fused_top_k=plan.budgets.fused_top_k)
    ranked = sorted(fusion.candidates, key=lambda c: c.fused_rank)
    top10 = [c.item_id for c in ranked[:10]]

    recall = question_recall_at_k(top10, gold_ids, 10)
    temporal_ok = all(c.published_at <= as_of for c in fusion.candidates)

    outcome = QuestionOutcome(recall_at_10=recall, temporal_ok=temporal_ok)
    diagnostic = {
        "id": entry.id,
        "category": entry.category,
        "answerable": entry.answerable,
        "gold_count": len(gold_ids),
        "retrieved_count": len(fusion.candidates),
        "recall_at_10": f"{recall:.4f}",
        "temporal_ok": temporal_ok,
    }
    return QuestionResult(outcome=outcome, diagnostic=diagnostic)


def assemble_report(
    outcomes: Sequence[QuestionOutcome],
    *,
    per_question: Sequence[dict[str, Any]],
    excluded: Sequence[dict[str, Any]],
    total_questions: int,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Pure report assembly: no DB, no clock (``meta`` carries any of that)."""
    metrics = aggregate_metrics(outcomes)
    supports = metric_supports(outcomes)
    gate_report = build_gate_report(metrics, supports=supports, thresholds=_COMPUTABLE_THRESHOLDS)
    not_evaluable = {
        name: {"reason": _NOT_EVALUABLE_REASON, "support": supports.get(name, 0)}
        for name in _NOT_EVALUABLE_METRICS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "gate": gate_report.to_dict(),
        "not_evaluable": not_evaluable,
        "questions": {
            "total": total_questions,
            "evaluated": len(outcomes),
            "excluded": list(excluded),
        },
        "per_question": list(per_question),
        "meta": meta,
    }


def exit_code(report: Mapping[str, Any]) -> int:
    """0 if every computable gate passed, else 1. Never influenced by
    ``not_evaluable`` metrics."""
    return 0 if report["gate"]["passed"] else 1


def _relative_to_repo(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _redact(database_url: str) -> str:
    parsed = urlsplit(database_url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    db = parsed.path
    return f"{parsed.scheme}://{host}{port}{db}"


def _print_table(report: Mapping[str, Any]) -> None:
    print(f"{'gate':<24} {'value':>10} {'threshold':>10} {'result':>8}")
    for result in report["gate"]["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{result['name']:<24} {result['value']:>10} {result['threshold']:>10} {status:>8}")
    reranker = report["gate"]["reranker"]
    print(f"reranker triggered: {reranker['triggered']} ({reranker['note']})")
    if report["not_evaluable"]:
        print("not evaluable (excluded from the gate):")
        for name in sorted(report["not_evaluable"]):
            print(f"  - {name}: {report['not_evaluable'][name]['reason']}")
    q = report["questions"]
    print(f"questions: {q['evaluated']}/{q['total']} evaluated, {len(q['excluded'])} excluded")
    overall = "PASS" if report["gate"]["passed"] else "FAIL"
    print(f"overall: {overall}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness.retrieval_gate")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL"),
        help="Postgres URL (default: $TEST_DATABASE_URL)",
    )
    parser.add_argument(
        "--questions", default=str(DEFAULT_QUESTIONS), help="path to seed questions JSONL"
    )
    parser.add_argument("--provider", default="mock", choices=("mock", "live"))
    parser.add_argument("--out", required=True, help="path to write the JSON report")
    args = parser.parse_args(argv)

    if args.provider == "live":
        print("provider=live is not provisioned, see #177", file=sys.stderr)
        return 2

    if psycopg is None:
        print("psycopg is not installed (see requirements-dev.txt)", file=sys.stderr)
        return 2
    if not args.database_url:
        print("no database URL: pass --database-url or set TEST_DATABASE_URL", file=sys.stderr)
        return 2

    questions_path = Path(args.questions)
    records = load_seed(questions_path)
    questions_sha256 = _file_sha256(questions_path)

    retrieval_url = ensure_retrieval_gate_database(args.database_url)
    with psycopg.connect(retrieval_url, autocommit=True) as conn:
        try:
            built = build_and_index_corpus(conn, records, questions_sha256=questions_sha256)
        except GateBuildError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        outcomes: list[QuestionOutcome] = []
        per_question: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for entry in built.manifest_entries:
            result = run_question(
                conn,
                entry,
                index_version_id=built.index_version_id,
                corpus_version_id=built.corpus_version_id,
            )
            if result.outcome is None:
                excluded.append({"id": entry.id, **result.diagnostic})
                continue
            outcomes.append(result.outcome)
            per_question.append(result.diagnostic)

    meta = {
        "database": _redact(retrieval_url),
        "provider": _PROVIDER_NAME,
        "embedding_model": _MODEL_NAME,
        "questions_path": _relative_to_repo(questions_path),
        "questions_sha256": questions_sha256,
        "corpus_version_id": built.corpus_version_id,
        "index_version_id": built.index_version_id,
        "index_reused": built.reused,
        "item_count": built.item_count,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    per_question.sort(key=lambda d: str(d["id"]))
    report = assemble_report(
        outcomes,
        per_question=per_question,
        excluded=excluded,
        total_questions=len(built.manifest_entries),
        meta=meta,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    _print_table(report)
    print(f"report written to {out_path}")
    return exit_code(report)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
