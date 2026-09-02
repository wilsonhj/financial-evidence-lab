"""Integration fixtures for retrieval index build/publish.

DB-backed tests need ``TEST_DATABASE_URL`` pointing at a disposable pgvector
Postgres with db/migrations applied; they skip cleanly otherwise. A local run
against the CI container looks like::

    TEST_DATABASE_URL=postgres://fel:fel-ci-only@localhost:55432/fel_test \\
        .venv/bin/python -m pytest packages/retrieval/tests -q

Retrieval index versions/items/embeddings are immutable (delete-forbidding
triggers), so the seed randomizes every id per test — reruns mint fresh rows
rather than colliding, and no teardown is possible or attempted.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult

try:  # driver is a dev dependency; integration tests require it
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - psycopg is in requirements-dev
    psycopg = None  # type: ignore[assignment]

from fel_retrieval import content_sha256

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def ensure_retrieval_database(base_url: str) -> str:
    """Create and migrate a dedicated ``<db>_retrieval`` sibling; return its URL.

    Retrieval integration tests commit into delete-immutable shared tables
    (``retrieval_index_versions``/``retrieval_items``/``retrieval_embeddings``,
    guarded by BEFORE DELETE triggers and an FK to ``corpus_versions``). Running
    them against the base ``TEST_DATABASE_URL`` permanently blocks the
    workers/ingestion suites' ``DELETE FROM corpus_versions`` cleanup, so they
    run against an isolated sibling database instead. Roles (``fel_app``) are
    cluster-level, so grants inside the migrations resolve there too.

    Idempotent: the database is created once (``DuplicateDatabase`` swallowed)
    and the non-idempotent migrations are applied only when the marker table is
    absent.
    """
    parsed = urlsplit(base_url)
    retrieval_db = parsed.path.lstrip("/") + "_retrieval"
    retrieval_url = urlunsplit(parsed._replace(path="/" + retrieval_db))

    with psycopg.connect(base_url, autocommit=True) as conn:
        try:
            conn.execute(f'CREATE DATABASE "{retrieval_db}"')  # noqa: S608 — derived name
        except psycopg.errors.DuplicateDatabase:
            pass

    repo_root = Path(__file__).resolve().parents[3]
    migrations = sorted(repo_root.glob("db/migrations/*.sql"))
    with psycopg.connect(retrieval_url, autocommit=True) as conn:
        marker = conn.execute("SELECT to_regclass('public.retrieval_index_versions')").fetchone()
        if marker is None or marker[0] is None:
            for path in migrations:
                conn.execute(path.read_text())
    return retrieval_url


_SENTENCES = [
    "Revenue was $100 million in fiscal 2025.",
    "Cost of sales was $40 million in fiscal 2025.",
    "Operating income reached $35 million for the year.",
    "Net income was $28 million, up from the prior year.",
    "Cash and equivalents totaled $52 million at year end.",
    "Total assets stood at $410 million as of December 31.",
]


@dataclass(frozen=True)
class SeededDocument:
    corpus_version_id: str
    document_id: str
    document_version_id: str
    fact_id: str
    table_id: str
    corpus: dict[str, Any]


def _seed_document(
    conn: Any,
    *,
    corpus_version_id: str | None = None,
    published_at: datetime | None = None,
) -> SeededDocument:
    """Insert a small immutable document and return the matching builder view.

    With both keyword arguments omitted the seeder mints its own draft
    ``corpus_versions`` row and stamps ``published_at`` with the current time —
    the original single-document corpus. Passing ``corpus_version_id`` links the
    document into an existing corpus instead (so callers can straddle several
    documents across one corpus), and ``published_at`` pins an explicit cutoff.
    """
    own_corpus = corpus_version_id is None
    if corpus_version_id is None:
        corpus_version_id = str(uuid.uuid4())
    published = published_at if published_at is not None else datetime.now(UTC)
    entity_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    document_version_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    table_id = str(uuid.uuid4())
    fact_id = str(uuid.uuid4())
    heading_path = ["ITEM 8", "FINANCIAL STATEMENTS"]

    canonical = "\n".join(_SENTENCES)
    spans: list[dict[str, Any]] = []
    offset = 0
    for sentence in _SENTENCES:
        start = offset
        end = start + len(sentence)
        spans.append(
            {
                "id": str(uuid.uuid4()),
                "section_id": section_id,
                "start_char": start,
                "end_char": end,
                "text": sentence,
                "text_hash": content_sha256(sentence),
                "heading_path": heading_path,
            }
        )
        offset = end + 1  # account for the "\n" separator

    conn.execute(
        "INSERT INTO documents (id, entity_id, accession, source_url, content_hash, "
        "storage_key, published_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            document_id,
            entity_id,
            f"acc-{uuid.uuid4()}",
            "https://example.test/doc",
            content_sha256(canonical),
            f"raw/{document_id}",
            published,
        ),
    )
    conn.execute(
        "INSERT INTO document_versions (id, document_id, parser_version, "
        "normalizer_version, canonical_text_key) VALUES (%s, %s, %s, %s, %s)",
        (document_version_id, document_id, "p/1", "n/1", f"text/sha256/{document_id}"),
    )
    conn.execute(
        "INSERT INTO sections (id, document_version_id, heading, heading_path, ord, "
        "start_char, end_char) VALUES (%s, %s, %s, %s, 0, 0, %s)",
        (section_id, document_version_id, "FINANCIAL STATEMENTS", heading_path, len(canonical)),
    )
    for span in spans:
        conn.execute(
            "INSERT INTO source_spans (id, document_version_id, section_id, start_char, "
            "end_char, text_hash) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                span["id"],
                document_version_id,
                section_id,
                span["start_char"],
                span["end_char"],
                span["text_hash"],
            ),
        )
    conn.execute(
        "INSERT INTO financial_facts (id, entity_id, document_version_id, concept, value, "
        "unit, period_type, source_span_id, fact_key) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'duration', %s, %s)",
        (
            fact_id,
            entity_id,
            document_version_id,
            "Revenues",
            "100000000",
            "USD",
            spans[0]["id"],
            f"revenues:{document_id[:8]}:USD",
        ),
    )
    conn.execute(
        "INSERT INTO tables_meta (id, document_version_id, section_id, ord, headers, rows) "
        "VALUES (%s, %s, %s, 0, %s::jsonb, %s::jsonb)",
        (
            table_id,
            document_version_id,
            section_id,
            json.dumps(["metric", "value"]),
            json.dumps([{"source_span_id": spans[1]["id"]}, {"source_span_id": None}]),
        ),
    )
    if own_corpus:
        conn.execute(
            "INSERT INTO corpus_versions (id, label, status) VALUES (%s, %s, 'draft')",
            (corpus_version_id, f"corpus-{corpus_version_id[:8]}"),
        )
    conn.execute(
        "INSERT INTO corpus_version_documents (corpus_version_id, document_version_id) "
        "VALUES (%s, %s)",
        (corpus_version_id, document_version_id),
    )

    corpus = {
        "entity_id": entity_id,
        "document_id": document_id,
        "document_version_id": document_version_id,
        "form": "10-K",
        "canonical_text": canonical,
        "source_spans": spans,
        "financial_facts": [{"id": fact_id, "source_span_id": spans[0]["id"], "period": "FY2025"}],
        "tables": [
            {
                "id": table_id,
                "section_id": section_id,
                "heading_path": heading_path,
                "rows": [
                    {"source_span_id": spans[1]["id"]},
                    {"source_span_id": None},
                ],
            }
        ],
    }
    return SeededDocument(
        corpus_version_id=corpus_version_id,
        document_id=document_id,
        document_version_id=document_version_id,
        fact_id=fact_id,
        table_id=table_id,
        corpus=corpus,
    )


@pytest.fixture(scope="session")
def retrieval_db_url() -> str:
    if TEST_DATABASE_URL is None or psycopg is None:
        pytest.skip("TEST_DATABASE_URL not configured (needs pgvector Postgres)")
    return ensure_retrieval_database(TEST_DATABASE_URL)


@pytest.fixture()
def pg_conn(retrieval_db_url: str) -> Iterator[Any]:
    with psycopg.connect(retrieval_db_url, autocommit=True) as conn:
        yield conn


@pytest.fixture()
def seed_corpus(pg_conn: Any) -> Callable[[], SeededDocument]:
    """Factory: seed a fresh single-document corpus (call again for a second one)."""

    def factory() -> SeededDocument:
        return _seed_document(pg_conn)

    return factory


@pytest.fixture()
def seed_document(pg_conn: Any) -> Callable[..., SeededDocument]:
    """Factory: seed one document, optionally into an existing corpus at a pinned
    ``published_at`` (call again to straddle several documents across one corpus)."""

    def factory(
        *, corpus_version_id: str | None = None, published_at: datetime | None = None
    ) -> SeededDocument:
        return _seed_document(
            pg_conn, corpus_version_id=corpus_version_id, published_at=published_at
        )

    return factory


# --- non-identity claim generation (#133) ----------------------------------
# The old identity generator copied ``claim.numeric = item.numeric``, so the
# per-citation numeric check compared a value with itself and could only ever
# pass: every numeric assertion in a test built on it was a tautology. The
# scripted provider below is the antidote. It is a ``StructuredLLMProvider``
# like any other: it sees only the rendered prompt, never the ``ContextItem``
# objects, and its claim numerics come from the script the test hands it. A
# number that agrees with the cited evidence therefore agrees because the test
# said so, and a number that disagrees is a real disagreement the verifier has
# to catch.


class ScriptedClaimProvider:
    """Deterministic ``StructuredLLMProvider`` emitting scripted claims JSON.

    It is handed the claims-output/v1 objects it must return, so the numbers a
    claim asserts are the test's, never a copy of a cited item's tuple: nothing
    here can see a ``ContextItem`` at all, only the rendered prompt. The prompt
    is recorded so a test can pin what the generator actually sent, and
    ``asserted_values`` exposes the scripted assertions so a test can show they
    differ from the evidence they are checked against.
    """

    provider = "scripted"
    model = "scripted-claims-v1"

    def __init__(self, claims: Sequence[Mapping[str, Any]], *, abstain: str | None = None) -> None:
        self._claims = [dict(claim) for claim in claims]
        self._abstain = abstain
        self.prompt: str | None = None

    @property
    def asserted_values(self) -> tuple[str | None, ...]:
        """The ``value`` each scripted claim asserts (``None`` where unset)."""
        values: list[str | None] = []
        for claim in self._claims:
            numeric = claim.get("numeric")
            values.append(str(numeric["value"]) if isinstance(numeric, dict) else None)
        return tuple(values)

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        self.prompt = "\n".join(str(message.get("content", "")) for message in request.messages)
        return StructuredModelResult(
            provider=self.provider,
            model=self.model,
            response_id="scripted-1",
            parsed={
                "claims": [dict(claim) for claim in self._claims],
                "abstain": {"reason": self._abstain} if self._abstain is not None else None,
            },
            refused=False,
            refusal=None,
            input_tokens=11,
            output_tokens=5,
            estimated_cost_usd=Decimal("0"),
            raw={},
        )


@pytest.fixture()
def scripted_claim() -> Callable[..., dict[str, Any]]:
    """Factory: one claims-output/v1 claim object with an independent numeric.

    ``citations`` is a sequence of ``(item_id, quote)`` pairs; ``numeric`` is
    the value the claim asserts, with optional unit/period, or ``None`` for a
    claim asserting no single scalar.
    """

    def factory(
        text: str,
        citations: Sequence[tuple[str, str]],
        *,
        value: str | None = None,
        unit: str | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        return {
            "text": text,
            "citations": [{"item_id": item_id, "quote": quote} for item_id, quote in citations],
            "numeric": (
                None if value is None else {"value": value, "unit": unit, "period": period}
            ),
        }

    return factory


@pytest.fixture()
def scripted_claim_provider() -> Callable[..., ScriptedClaimProvider]:
    """Factory for :class:`ScriptedClaimProvider` (see #133)."""

    def factory(
        claims: Sequence[Mapping[str, Any]], *, abstain: str | None = None
    ) -> ScriptedClaimProvider:
        return ScriptedClaimProvider(claims, abstain=abstain)

    return factory
