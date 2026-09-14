"""Real fixture-transport worker preparation for the dedicated #108 smoke.

Only platform bootstrap and queue insertion use SQL writes here. Evidence is
produced by the actual worker process; corpus publication uses production helpers.
The manifest contains public synthetic evidence and IDs, never credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess  # nosec B404 — bounded acceptance subprocesses, no shell
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fel_workers.ingestion.company_facts import entity_id_for_cik
from fel_workers.ingestion.pipeline import create_corpus_version, publish_corpus_version
from fel_workers.queue import enqueue

FIXTURES = Path(__file__).resolve().parents[1] / "datasets" / "reader-prod-smoke"
NAMES = ("original", "amendment1", "amendment2", "future")
AS_OF = "2026-06-01T00:00:00Z"


def require_target(target: str) -> None:
    """Require two explicit matching designations, never default to production."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}", target):
        raise ValueError("A named dedicated smoke target is required")
    if os.environ.get("FEL_READER_SMOKE_TARGET") != target:
        raise ValueError("FEL_READER_SMOKE_TARGET must match the dedicated target")


def checked_outcomes(jobs: list[dict[str, Any]], ingestions: list[dict[str, Any]]) -> None:
    """Exit zero from the worker does not prove ingestion succeeded."""
    if len(jobs) != len(NAMES) or any(row["status"] != "succeeded" for row in jobs):
        raise RuntimeError("Expected four successful smoke queue jobs")
    if len(ingestions) != len(NAMES) or any(
        row["status"] != "succeeded" or not row["document_version_id"] for row in ingestions
    ):
        raise RuntimeError("Expected four successful, versioned smoke ingestions")


def setup(database_url: str, storage: Path, target: str) -> dict[str, Any]:
    require_target(target)
    storage.mkdir(parents=True, exist_ok=True)
    marker = storage / ".reader-smoke-target"
    if marker.exists() and marker.read_text() != target:
        raise ValueError("Storage belongs to a different smoke target")
    if not marker.exists() and any(storage.iterdir()):
        raise ValueError("Initial smoke storage must be empty")
    marker.write_text(target)
    identity = {key: str(uuid4()) for key in ("org", "user", "denied_user", "workspace")}
    identity["entity"] = entity_id_for_cik("9999998")
    fixtures = json.loads((FIXTURES / "manifest.json").read_text())
    with psycopg.connect(database_url) as conn:
        # Never mix acceptance data with an existing evidence database.
        existing = conn.execute("SELECT EXISTS(SELECT 1 FROM documents)").fetchone()
        if existing is None or existing[0]:
            raise ValueError("Smoke setup requires an empty evidence database")
        conn.execute(
            "INSERT INTO organizations(id,name) VALUES (%s,'Reader smoke')", (identity["org"],)
        )
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'owner')",
            (identity["org"], identity["user"]),
        )
        conn.execute(
            "INSERT INTO workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of) "
            "VALUES (%s,%s,'Reader smoke',%s,'USD','FY',%s)",
            (identity["workspace"], identity["org"], identity["entity"], AS_OF),
        )
        jobs = []
        for index, document in enumerate(fixtures["documents"]):
            jobs.append(
                enqueue(
                    conn,
                    kind="sec_filing_fetch",
                    queue="reader-smoke",
                    max_attempts=1,
                    payload={
                        "url": document["url"],
                        "accession": f"0009999998-26-00000{index + 1}",
                        "cik": "9999998",
                        "form": "10-Q" if index in (0, 3) else "10-Q/A",
                        "filed_on": ("2026-07-01" if index == 3 else f"2026-04-0{index + 1}"),
                        "period_start": "2026-01-01",
                        "period_end": "2026-03-31",
                    },
                )
            )
    environment = os.environ.copy()
    for name in (
        "FEL_SEC_LIVE",
        "FEL_MOCK_SMOKE",
        "FEL_ALLOW_MOCK_LLM",
        "PORT",
        "FEL_WORKER_HEALTH_PORT",
    ):
        environment.pop(name, None)
    environment.update(
        FEL_DATABASE_URL=database_url,
        FEL_STORAGE_DIR=str(storage.resolve()),
        FEL_FIXTURE_DIR=str(FIXTURES),
        FEL_FIXTURE_INGEST="1",
        FEL_WORKER_DB_ROLE="fel_worker",
    )
    result = subprocess.run(  # nosec B603 — fixed worker module and literal queue arguments
        [
            sys.executable,
            "-m",
            "fel_workers",
            "run",
            "--queue",
            "reader-smoke",
            "--max-iterations",
            "4",
        ],
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )
    # Worker logs may contain operator configuration. Do not copy them into artifacts.
    if result.returncode:
        raise RuntimeError("Fixture worker process failed; inspect restricted service logs")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT id,status FROM jobs WHERE id=ANY(%s::uuid[])", (jobs,)
        ).fetchall()
        ingestions = conn.execute(
            "SELECT ir.status,ir.document_version_id FROM ingestion_runs ir "
            "JOIN documents d ON d.id=ir.document_id WHERE d.entity_id=%s",
            (identity["entity"],),
        ).fetchall()
        checked_outcomes(rows, ingestions)
        documents = {}
        for index, name in enumerate(NAMES):
            row = conn.execute(
                "SELECT d.id,d.period_start,d.period_end,dv.id AS version,dv.canonical_text_key "
                "FROM documents d JOIN document_versions dv ON dv.document_id=d.id "
                "WHERE d.accession=%s AND dv.status='parsed'",
                (f"0009999998-26-00000{index + 1}",),
            ).fetchone()
            if (
                row is None
                or str(row["period_start"]) != "2026-01-01"
                or str(row["period_end"]) != "2026-03-31"
            ):
                raise RuntimeError("Worker lost the explicitly supplied reporting period")
            span = conn.execute(
                "SELECT ss.id,ss.section_id,ss.start_char,ss.end_char,ss.text_hash "
                "FROM source_spans ss JOIN sections s ON s.id=ss.section_id "
                "WHERE ss.document_version_id=%s AND s.heading='Item 2. Management discussion' "
                "ORDER BY ss.start_char LIMIT 1",
                (row["version"],),
            ).fetchone()
            if span is None:
                raise RuntimeError("Worker produced no required non-first-section citation")
            text = (storage / row["canonical_text_key"]).read_text()
            quote = text[span["start_char"] : span["end_char"]]
            if "sha256:" + hashlib.sha256(quote.encode()).hexdigest() != span["text_hash"]:
                raise RuntimeError("Worker citation hash does not match its canonical bytes")
            documents[name] = {
                "id": str(row["id"]),
                "version": str(row["version"]),
                "span": str(span["id"]),
                "section": str(span["section_id"]),
                "quote": quote,
                "text_hash": span["text_hash"],
                "canonical_key": row["canonical_text_key"],
                "canonical_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "start_char": span["start_char"],
                "end_char": span["end_char"],
            }
    # Publication helpers expect tuple rows; these are production operations,
    # not hand-authored corpus inserts or document/version mutations.
    with psycopg.connect(database_url) as conn:
        pinned = create_corpus_version(
            conn,
            label="Reader original pin",
            document_version_ids=[documents["original"]["version"]],
        )
        publish_corpus_version(conn, pinned)
        current = create_corpus_version(
            conn,
            label="Reader complete history",
            document_version_ids=[d["version"] for d in documents.values()],
        )
        publish_corpus_version(conn, current)
    return {
        "schema_version": "reader-prod-smoke/v1",
        "target": target,
        **identity,
        "as_of": AS_OF,
        "corpus": current,
        "pinned_corpus": pinned,
        "documents": documents,
        "jobs": jobs,
    }


def blob_fault(manifest: dict[str, Any], storage: Path, target: str, *, restore: bool) -> None:
    """Reversible byte mutation, restricted to the manifest's dedicated storage."""
    require_target(target)
    if manifest.get("target") != target or (storage / ".reader-smoke-target").read_text() != target:
        raise ValueError("Manifest and storage must identify the dedicated smoke target")
    document = manifest["documents"]["amendment2"]
    root = storage.resolve()
    path = (root / document["canonical_key"]).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Canonical object must remain inside dedicated storage")
    backup = root / ".reader-smoke-original"
    if restore:
        raw = backup.read_bytes()
        if hashlib.sha256(raw).hexdigest() != document["canonical_sha256"]:
            raise ValueError("Refusing an invalid restoration backup")
        path.write_bytes(raw)
        backup.unlink()
        return
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != document["canonical_sha256"]:
        raise ValueError("Canonical object is already changed")
    with backup.open("xb") as output:
        output.write(raw)
    backup.chmod(0o600)
    offset = len(raw.decode()[: document["start_char"]].encode())
    changed = bytearray(raw)
    changed[offset] = ord("X") if changed[offset] != ord("X") else ord("Y")
    path.write_bytes(changed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "corrupt", "restore"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dedicated-target", required=True)
    args = parser.parse_args()
    storage = Path(os.environ["FEL_STORAGE_DIR"])
    if args.action == "setup":
        manifest = setup(os.environ["FEL_DATABASE_URL"], storage, args.dedicated_target)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    else:
        blob_fault(
            json.loads(args.manifest.read_text()),
            storage,
            args.dedicated_target,
            restore=args.action == "restore",
        )


if __name__ == "__main__":
    main()
