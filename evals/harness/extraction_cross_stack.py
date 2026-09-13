"""Synthetic evidence setup and real durable worker for #61 browser acceptance.

Run only against an isolated, migrated PostgreSQL database. The browser creates
the run through the production Next.js proxy and mounted FastAPI application.
Only the model reply is mocked; queue claims, validation, persistence, review,
correction, immutable history and SSE all use production implementations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_providers.mocks import MockSecClient, MockStructuredLLMProvider
from fel_workers.consumer import run_worker
from fel_workers.storage import LocalDirStorageProvider, apply_worker_db_role

SOURCE_TEXT = "Annual recurring revenue was $100 million at June 30, 2026."


class ScopedMock(MockStructuredLLMProvider):
    """Bind committed model fixtures to this execution's real evidence IDs."""

    def __init__(self, manifest: dict[str, str]) -> None:
        super().__init__()
        self.identities = {
            "source_span_id": manifest["span"],
            "document_version_id": manifest["version"],
            "entity_id": manifest["entity"],
        }

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = super().generate_structured(request)

        def scoped(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: self.identities.get(key, scoped(item)) for key, item in value.items()}
            if isinstance(value, list):
                return [scoped(item) for item in value]
            return value

        return replace(result, parsed=scoped(result.parsed))


def seed(database_url: str, storage_dir: Path) -> dict[str, str]:
    """Insert only source/configuration rows; never seed runs or approvals."""
    ids = {
        key: str(uuid4())
        for key in (
            "org",
            "user",
            "workspace",
            "entity",
            "policy",
            "document",
            "version",
            "section",
            "span",
            "corpus",
        )
    }
    digest = "sha256:" + hashlib.sha256(SOURCE_TEXT.encode()).hexdigest()
    key = "canonical/" + ids["version"]
    LocalDirStorageProvider(storage_dir).put(key, SOURCE_TEXT.encode())
    with psycopg.connect(database_url) as conn:
        conn.execute("INSERT INTO organizations(id,name) VALUES (%s,'Cross-stack')", (ids["org"],))
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'owner')",
            (ids["org"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of) "
            "VALUES (%s,%s,'Cross-stack',%s,'USD','FY','2026-07-01T00:00:00Z')",
            (ids["workspace"], ids["org"], ids["entity"]),
        )
        conn.execute(
            "INSERT INTO extraction_policies(id,org_id,version,created_by) VALUES (%s,%s,1,%s)",
            (ids["policy"], ids["org"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO documents(id,entity_id,accession,form,source_url,content_hash,storage_key,"
            "published_at,filed_at) VALUES (%s,%s,%s,'10-Q','https://example.invalid/synthetic',"
            "%s,%s,'2026-07-01Z','2026-07-01Z')",
            (ids["document"], ids["entity"], ids["document"], digest, key),
        )
        conn.execute(
            "INSERT INTO document_versions(id,document_id,parser_version,normalizer_version,"
            "status,canonical_text_key) VALUES (%s,%s,'parser/v1','normalizer/v1','parsed',%s)",
            (ids["version"], ids["document"], key),
        )
        conn.execute(
            "INSERT INTO sections(id,document_version_id,heading,heading_path,ord,start_char,"
            "end_char) VALUES (%s,%s,'Results',ARRAY['Results'],0,0,%s)",
            (ids["section"], ids["version"], len(SOURCE_TEXT)),
        )
        conn.execute(
            "INSERT INTO source_spans(id,document_version_id,section_id,start_char,end_char,"
            "text_hash) VALUES (%s,%s,%s,0,%s,%s)",
            (ids["span"], ids["version"], ids["section"], len(SOURCE_TEXT), digest),
        )
        conn.execute(
            "INSERT INTO corpus_versions(id,label,status) VALUES (%s,'Sources','superseded')",
            (ids["corpus"],),
        )
        conn.execute(
            "INSERT INTO corpus_version_documents(corpus_version_id,document_version_id) "
            "VALUES (%s,%s)",
            (ids["corpus"], ids["version"]),
        )
    return ids


def work(database_url: str, storage_dir: Path, manifest: dict[str, str]) -> None:
    """Claim the API-created job with the production lease-fenced dispatcher."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_worker_db_role(conn)
        completed = run_worker(
            conn,
            LocalDirStorageProvider(storage_dir),
            MockSecClient(),
            queue_name="extraction",
            max_iterations=1,
            structured_llm=ScopedMock(manifest),
        )
    if completed != 1:
        raise RuntimeError("Expected exactly one successfully processed extraction job")


def verify(database_url: str, manifest: dict[str, str], run_id: str, record_id: str) -> None:
    """Verify durable terminal state and two linked immutable approval versions."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        run = conn.execute(
            "SELECT status,corpus_version_id FROM extraction_runs WHERE id=%s AND org_id=%s",
            (run_id, manifest["org"]),
        ).fetchone()
        job = conn.execute(
            "SELECT status,attempts FROM jobs WHERE id=%s AND org_id=%s", (run_id, manifest["org"])
        ).fetchone()
        versions = conn.execute(
            "SELECT id,version,parent_version_id,evidence_manifest,validation_context "
            "FROM approved_extraction_versions WHERE record_id=%s AND org_id=%s ORDER BY version",
            (record_id, manifest["org"]),
        ).fetchall()
        events = conn.execute(
            "SELECT event_type FROM extraction_run_events WHERE run_id=%s AND org_id=%s",
            (run_id, manifest["org"]),
        ).fetchall()
    if run != {"status": "succeeded", "corpus_version_id": UUID(manifest["corpus"])}:
        raise RuntimeError("Run did not retain the pinned corpus and reach succeeded")
    if job != {"status": "succeeded", "attempts": 1}:
        raise RuntimeError("Durable queue job was not claimed and completed exactly once")
    if len(versions) != 2 or [v["version"] for v in versions] != [1, 2]:
        raise RuntimeError("Expected original approval and one immutable correction")
    if (
        versions[0]["parent_version_id"] is not None
        or versions[1]["parent_version_id"] != versions[0]["id"]
    ):
        raise RuntimeError("Immutable correction does not point to its original version")
    for version in versions:
        if {str(e["source_span_id"]) for e in version["evidence_manifest"]} != {manifest["span"]}:
            raise RuntimeError("Approved evidence lost its actual source span")
        if {p["run_id"] for p in version["validation_context"]["source_runs"]} != {run_id}:
            raise RuntimeError("Approved validation context lost the originating run")
    if not {"review_waiting", "review_completed", "run_succeeded"}.issubset(
        {row["event_type"] for row in events}
    ):
        raise RuntimeError("Review lifecycle was not durably published")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "work", "verify"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run")
    parser.add_argument("--record")
    args = parser.parse_args()
    database_url = os.environ["FEL_DATABASE_URL"]
    storage = Path(os.environ["FEL_STORAGE_DIR"])
    if os.environ.get("FEL_AUTH_MODE") != "mock" or os.environ.get("FEL_ALLOW_MOCK_LLM") != "1":
        parser.error("Acceptance requires explicit mock auth and model opt-in")
    if args.action == "seed":
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(seed(database_url, storage)))
    elif args.action == "work":
        work(database_url, storage, json.loads(args.manifest.read_text()))
    else:
        if not args.run or not args.record:
            parser.error("verify requires --run and --record")
        verify(database_url, json.loads(args.manifest.read_text()), args.run, args.record)


if __name__ == "__main__":
    main()
