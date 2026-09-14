"""Opt-in isolated local PostgreSQL + real HTTP extraction acceptance.

The runner owns one Uvicorn process. It never drops data or modifies application
settings to improve results. See apps/api/EXTRACTION_LOAD.md before execution.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

from app.auth import make_mock_token
from app.config import settings
from benchmarks.extraction_load_fixture import DIGEST, SOURCE_TEXT, seed, state, verify, work
from benchmarks.extraction_load_report import report


def measure(
    operation: str, ids: dict[str, Any], base: str, barrier: threading.Barrier
) -> dict[str, Any]:
    headers = {"Authorization": "Bearer " + make_mock_token(ids["org"], ids["user"], "owner")}
    row: dict[str, Any] = dict(operation=operation, status=None, verified=False, error=None)
    with httpx.Client(base_url=base, timeout=60) as client:
        barrier.wait(timeout=30)
        row["start_ns"] = time.perf_counter_ns()
        try:
            if operation == "create":
                response = client.post(
                    f"/v1/workspaces/{ids['workspace']}/extraction-runs",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json=dict(
                        entity_id=ids["entity"],
                        as_of="2026-07-01T00:00:00Z",
                        modes=["kpi"],
                        source_span_ids=[ids["span"]],
                        corpus_version_id=ids["corpus"],
                    ),
                )
                row["status"] = response.status_code
                response.raise_for_status()
                ids["run"] = response.json()["id"]
            elif operation == "review":
                proposals = ids["snapshot"]["proposals"]
                response = client.post(
                    "/v1/extractions/review",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json=dict(
                        action="accept",
                        extraction_ids=[str(p["id"]) for p in proposals],
                        expected_versions={str(p["id"]): p["version"] for p in proposals},
                        reason="Explicit synthetic load acceptance",
                    ),
                )
                row["status"] = response.status_code
                response.raise_for_status()
                if len(response.json()["approved_record_ids"]) != 100:
                    raise RuntimeError("Incorrect review result count")
            else:
                before, expected = ids["resume"]
                with client.stream(
                    "GET",
                    f"/v1/extraction-runs/{ids['run']}/events",
                    headers={**headers, "Last-Event-ID": str(before)},
                ) as response:
                    row["status"] = response.status_code
                    response.raise_for_status()
                    frame: list[str] = []
                    for line in response.iter_lines():
                        if line:
                            frame.append(line)
                        elif frame:
                            fields = dict(
                                item.split(": ", 1)
                                for item in frame
                                if ": " in item and not item.startswith(":")
                            )
                            frame = []
                            if "data" not in fields:
                                continue
                            payload = json.loads(fields["data"])
                            if (
                                fields.get("id") != str(expected["id"])
                                or fields.get("event") != expected["event_type"]
                                or payload["type"] != expected["event_type"]
                                or payload != expected["projected"]
                            ):
                                raise RuntimeError("Unexpected durable resume event")
                            break
                    else:
                        raise RuntimeError("No complete eligible durable event")
            row["end_ns"] = time.perf_counter_ns()
            row["verified"] = True
        except Exception as exc:
            row["end_ns"] = time.perf_counter_ns()
            # Exception strings can contain URLs/response bodies: retain only type.
            row["error"] = type(exc).__name__
    return row


def wave(
    database: str,
    storage: Path,
    base: str,
    count: int,
    phase: str,
    number: int,
    output: Path,
    rows: list[dict[str, Any]],
) -> None:
    users: list[dict[str, Any]] = [seed(database, storage) for _ in range(count)]

    def flush() -> None:
        output.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def operation(name: str) -> None:
        barrier = threading.Barrier(count)
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
            futures = [executor.submit(measure, name, ids, base, barrier) for ids in users]
            for user, future in enumerate(futures):
                try:
                    row = future.result()
                except Exception as exc:
                    now = time.perf_counter_ns()
                    row = dict(
                        operation=name,
                        status=None,
                        verified=False,
                        error=type(exc).__name__,
                        start_ns=now,
                        end_ns=now,
                    )
                row.update(
                    phase=phase,
                    wave=number,
                    user=user,
                    actor_id=users[user]["user"],
                    run_id=users[user].get("run"),
                )
                rows.append(row)
        flush()
        if any(r["error"] for r in rows):
            raise RuntimeError("Measured operation failed; raw evidence retained")

    operation("create")
    # Single owned consumer, no competing worker: process each actual next queue job.
    remaining = {ids["run"]: ids for ids in users}
    while remaining:
        with psycopg.connect(database) as conn:
            next_job = conn.execute(
                "SELECT id FROM jobs WHERE queue='extraction' AND status='queued' AND "
                "available_at<=now() ORDER BY priority,created_at LIMIT 1"
            ).fetchone()
        if next_job is None or str(next_job[0]) not in remaining:
            raise RuntimeError("Unexpected isolated queue contents")
        ids = remaining.pop(str(next_job[0]))
        work(database, storage, ids)
        ids["snapshot"] = state(database, ids)
        events = ids["snapshot"]["events"]
        ids["resume"] = (events[-2]["id"], events[-1])
        if events[-1]["event_type"] != "review_waiting":
            raise RuntimeError("Worker did not reach durable review waiting")
    operation("waiting_reconnect")
    operation("review")
    for ids in users:
        verify(database, ids)
        events = state(database, ids)["events"]
        ids["resume"] = (events[-2]["id"], events[-1])
        if events[-1]["event_type"] != "run_succeeded":
            raise RuntimeError("Review did not reach durable success")
    operation("terminal_reconnect")
    flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8231)
    parser.add_argument("--waves", type=int, default=4)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    database = os.environ.get("FEL_DATABASE_URL", "")
    connection = psycopg.conninfo.conninfo_to_dict(database)
    if connection.get("host") not in ("127.0.0.1", "localhost") or not str(
        connection.get("dbname", "")
    ).startswith("fel_load"):
        parser.error("Requires a dedicated local database named fel_load*, already migrated")
    if args.waves < 4 or not 1024 <= args.port <= 65535:
        parser.error("At least four measured waves and an unprivileged port are required")
    if (
        os.environ.get("FEL_AUTH_MODE") != "mock"
        or os.environ.get("FEL_ALLOW_MOCK_LLM") != "1"
        or os.environ.get("FEL_WORKER_DB_ROLE") != "fel_worker"
    ):
        parser.error("Requires explicit mock auth/model and fel_worker role")
    args.output.mkdir(parents=True, exist_ok=False)
    storage = Path(os.environ["FEL_STORAGE_DIR"])
    with psycopg.connect(database, row_factory=dict_row) as conn:
        unfinished = conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()
        assert unfinished is not None
        if unfinished["n"]:
            parser.error("Dedicated database has unfinished jobs")
        pg = {}
        for key in (
            "server_version",
            "fsync",
            "synchronous_commit",
            "shared_buffers",
            "max_connections",
        ):
            setting = conn.execute("SELECT current_setting(%s) AS value", (key,)).fetchone()
            assert setting is not None
            pg[key] = setting["value"]
    config = settings()
    metadata = dict(
        platform=platform.platform(),
        started_at_unix=time.time(),
        host_load=os.getloadavg(),
        physical_memory_bytes=(
            int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
            if sys.platform == "darwin"
            else os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        ),
        harness_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.glob("*.py")
        },
        cpu_count=os.cpu_count(),
        python=sys.version,
        api_processes=1,
        db_pool_min=config.db_pool_min,
        db_pool_max=config.db_pool_max,
        rate_limit_qps=config.rate_limit_qps,
        rate_limit_burst=config.rate_limit_burst,
        postgres=pg,
        source_bytes=len(SOURCE_TEXT.encode()),
        source_hash=DIGEST,
        proposal_count=100,
        synthetic=True,
        worker_and_setup_excluded=True,
        timings_include_auth_pool_wait_and_full_http=True,
    )
    for name, command in (
        ("commit", ["git", "rev-parse", "HEAD"]),
        ("tree", ["git", "rev-parse", "HEAD^{tree}"]),
        ("worktree_status", ["git", "status", "--porcelain"]),
    ):
        metadata[name] = subprocess.check_output(command, text=True).strip()
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    rows: list[dict[str, Any]] = []
    failure = None
    base = f"http://127.0.0.1:{args.port}"
    with socket.socket() as listener, (args.output / "server.log").open("w") as log:
        listener.bind(("127.0.0.1", args.port))
        listener.listen(128)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--fd",
                str(listener.fileno()),
                "--no-access-log",
            ],
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(timeout=1) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Owned API exited during startup")
                    try:
                        if client.get(base + "/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Owned API did not become healthy")
            wave(database, storage, base, 1, "preflight", 0, args.output / "samples.jsonl", rows)
            if not args.preflight_only:
                wave(database, storage, base, 25, "warmup", 0, args.output / "samples.jsonl", rows)
                for index in range(args.waves):
                    wave(
                        database,
                        storage,
                        base,
                        25,
                        "measured",
                        index,
                        args.output / "samples.jsonl",
                        rows,
                    )
        except Exception as exc:
            failure = type(exc).__name__
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    result = report(rows, waves=args.waves)
    result["execution_error"] = failure
    result["passed"] = result["passed"] and failure is None and not args.preflight_only
    (args.output / "report.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
