"""Synthetic load input; all proposals still pass through the production worker."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.extraction.events import project
from fel_providers.interfaces import StructuredGenerationRequest, StructuredModelResult
from fel_providers.mocks import MockSecClient
from fel_workers.consumer import run_worker
from fel_workers.storage import LocalDirStorageProvider, apply_worker_db_role
from harness.extraction_cross_stack import ScopedMock

DATES = [(date(2026, 6, 30) - timedelta(days=i)).isoformat() for i in range(100)]
SOURCE_TEXT = "\n".join(f"Annual recurring revenue was $100 million at {day}." for day in DATES)
DIGEST = "sha256:" + hashlib.sha256(SOURCE_TEXT.encode()).hexdigest()


class BulkMock(ScopedMock):
    """100 distinct dated proposals; mock token counts are not model performance."""

    def generate_structured(self, request: StructuredGenerationRequest) -> StructuredModelResult:
        result = super().generate_structured(request)
        if request.schema_name != "kpi":
            return result
        parsed: Any = result.parsed
        if not isinstance(parsed, dict) or not parsed.get("proposals"):
            raise RuntimeError("Missing base mock proposal")
        proposals = []
        for day in DATES:
            item = copy.deepcopy(parsed["proposals"][0])
            item["period"] = {"type": "instant", "instant": day}
            proposals.append(item)
        return replace(result, parsed={"proposals": proposals, "notes": None})


def seed(database_url: str, storage_dir: Path) -> dict[str, str]:
    """Seed platform/source configuration only; never seed runs or approvals."""
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
    key = "canonical/" + ids["version"]
    LocalDirStorageProvider(storage_dir).put(key, SOURCE_TEXT.encode())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO organizations(id,name) VALUES (%s,'Load acceptance')", (ids["org"],)
        )
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'owner')",
            (ids["org"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO "
            "workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of) "
            "VALUES (%s,%s,'Load acceptance',%s,'USD','FY','2026-07-01Z')",
            (ids["workspace"], ids["org"], ids["entity"]),
        )
        conn.execute(
            "INSERT INTO extraction_policies(id,org_id,version,created_by) VALUES (%s,%s,1,%s)",
            (ids["policy"], ids["org"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO "
            "documents(id,entity_id,accession,form,source_url,content_hash,storage_key,"
            "published_at,filed_at) VALUES (%s,%s,%s,'10-Q','https://example.invalid/load',"
            "%s,%s,'2026-07-01Z','2026-07-01Z')",
            (ids["document"], ids["entity"], ids["document"], DIGEST, key),
        )
        conn.execute(
            "INSERT INTO "
            "document_versions(id,document_id,parser_version,normalizer_version,status,"
            "canonical_text_key) VALUES (%s,%s,'parser/v1','normalizer/v1','parsed',%s)",
            (ids["version"], ids["document"], key),
        )
        conn.execute(
            "INSERT INTO "
            "sections(id,document_version_id,heading,heading_path,ord,start_char,end_char) "
            "VALUES (%s,%s,'Results',ARRAY['Results'],0,0,%s)",
            (ids["section"], ids["version"], len(SOURCE_TEXT)),
        )
        conn.execute(
            "INSERT INTO "
            "source_spans(id,document_version_id,section_id,start_char,end_char,text_hash) "
            "VALUES (%s,%s,%s,0,%s,%s)",
            (ids["span"], ids["version"], ids["section"], len(SOURCE_TEXT), DIGEST),
        )
        conn.execute(
            "INSERT INTO corpus_versions(id,label,status) VALUES (%s,'Load "
            "synthetic','superseded')",
            (ids["corpus"],),
        )
        conn.execute(
            "INSERT INTO corpus_version_documents(corpus_version_id,document_version_id) "
            "VALUES (%s,%s)",
            (ids["corpus"], ids["version"]),
        )
    return ids


def work(database_url: str, storage_dir: Path, manifest: dict[str, str]) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_worker_db_role(conn)
        count = run_worker(
            conn,
            LocalDirStorageProvider(storage_dir),
            MockSecClient(),
            queue_name="extraction",
            max_iterations=1,
            structured_llm=BulkMock(manifest),
        )
    if count != 1:
        raise RuntimeError("Worker did not complete exactly one job")


def state(database_url: str, ids: dict[str, str]) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        proposals = conn.execute(
            "SELECT id,state,version FROM extraction_proposals WHERE run_id=%s AND "
            "org_id=%s ORDER BY id",
            (ids["run"], ids["org"]),
        ).fetchall()
        events = conn.execute(
            "SELECT id,run_id,event_type,payload,created_at AS occurred_at "
            "FROM extraction_run_events WHERE run_id=%s AND "
            "org_id=%s ORDER BY id",
            (ids["run"], ids["org"]),
        ).fetchall()
    if len(proposals) != 100 or not events:
        raise RuntimeError("Expected 100 worker-produced proposals and durable events")
    for event in events:
        event["projected"] = project(event)
    return dict(proposals=proposals, events=events)


def verify(database_url: str, ids: dict[str, str]) -> None:
    current = state(database_url, ids)
    if any(p["state"] != "accepted" or p["version"] != 2 for p in current["proposals"]):
        raise RuntimeError("Expected 100 accepted version-2 proposals")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        run = conn.execute(
            "SELECT status,corpus_version_id FROM extraction_runs WHERE id=%s AND org_id=%s",
            (ids["run"], ids["org"]),
        ).fetchone()
        job = conn.execute(
            "SELECT status,attempts FROM jobs WHERE id=%s AND org_id=%s", (ids["run"], ids["org"])
        ).fetchone()
        versions = conn.execute(
            "SELECT version,parent_version_id,evidence_manifest,validation_context FROM "
            "approved_extraction_versions WHERE org_id=%s",
            (ids["org"],),
        ).fetchall()
    if run != {
        "status": "succeeded",
        "corpus_version_id": UUID(ids["corpus"]),
    } or job != {"status": "succeeded", "attempts": 1}:
        raise RuntimeError("Run/job state or source pin mismatch")
    if len(versions) != 100:
        raise RuntimeError("Expected exactly 100 immutable approved versions")
    for version in versions:
        if version["version"] != 1 or version["parent_version_id"] is not None:
            raise RuntimeError("Unexpected approved history")
        evidence = version["evidence_manifest"]
        if (
            len(evidence) != 1
            or str(evidence[0]["source_span_id"]) != ids["span"]
            or evidence[0]["text_hash"] != DIGEST
        ):
            raise RuntimeError("Approved source/evidence mismatch")
        if {row["run_id"] for row in version["validation_context"]["source_runs"]} != {ids["run"]}:
            raise RuntimeError("Approved source run provenance mismatch")
