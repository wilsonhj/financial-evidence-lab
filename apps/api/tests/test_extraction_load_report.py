"""The acceptance report must reject incomplete, serial, or failing measurements."""

import copy

import pytest

from benchmarks.extraction_load_report import OPERATIONS, report


def samples():
    return [
        dict(
            operation=operation,
            phase="measured",
            wave=wave,
            user=user,
            actor_id=f"actor-{wave}-{user}",
            start_ns=wave * 10**10,
            end_ns=wave * 10**10 + 100_000_000,
            status=202 if operation == "create" else 200,
            verified=True,
            error=None,
        )
        for operation in OPERATIONS
        for wave in range(4)
        for user in range(25)
    ]


def test_complete_concurrent_observations_pass():
    result = report(samples())
    assert result["passed"]
    assert result["operations"]["review"]["p95_ms"] == 100
    assert result["operations"]["review"]["min_wave_overlap"] == 25


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate", "error", "status", "unverified", "serial", "slow", "same_actor"],
)
def test_report_rejects_invalid_evidence(change):
    rows = samples()
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = copy.deepcopy(rows[-2])
    elif change == "error":
        rows[0]["error"] = "timeout"
    elif change == "status":
        rows[0]["status"] = 429
    elif change == "unverified":
        rows[0]["verified"] = False
    elif change == "serial":
        for row in rows:
            row["start_ns"] += row["user"] * 200_000_000
            row["end_ns"] += row["user"] * 200_000_000
    elif change == "same_actor":
        for row in rows:
            row["actor_id"] = "one-actor"
    elif change == "slow":
        for row in rows:
            row["end_ns"] = row["start_ns"] + 2_000_000_000
    assert not report(rows)["passed"]


def test_nearest_rank_and_strict_threshold_without_warmup_contamination():
    rows = samples()
    create = [row for row in rows if row["operation"] == "create"]
    for index, row in enumerate(create):
        row["end_ns"] = row["start_ns"] + (index + 1) * 1_000_000
    rows.append(dict(create[0], phase="warmup", end_ns=999_000_000_000))
    assert report(rows)["operations"]["create"]["p95_ms"] == 95
    for row in create:
        row["end_ns"] = row["start_ns"] + 500_000_000
    assert not report(rows)["passed"]


def test_bulk_mock_produces_100_distinct_source_supported_dates():
    from uuid import uuid4

    from benchmarks.extraction_load_fixture import DATES, SOURCE_TEXT, BulkMock
    from fel_providers.interfaces import StructuredGenerationRequest

    ids = {key: str(uuid4()) for key in ("span", "version", "entity")}
    result = BulkMock(ids).generate_structured(
        StructuredGenerationRequest(
            schema_name="kpi",
            schema_version="load/v1",
            json_schema={},
            messages=[],
            max_output_tokens=4096,
        )
    )
    proposals = result.parsed["proposals"]
    assert len(proposals) == 100
    assert {p["period"]["instant"] for p in proposals} == set(DATES)
    for proposal in proposals:
        assert proposal["period"]["instant"] in SOURCE_TEXT
        assert proposal["evidence"][0]["source_span_id"] == ids["span"]
        assert proposal["evidence"][0]["document_version_id"] == ids["version"]


@pytest.mark.parametrize("kind", ["correct", "comment_only", "wrong_payload", "wrong_id", "error"])
def test_reconnect_requires_complete_exact_durable_frame(monkeypatch, kind):
    import json
    import threading
    from uuid import uuid4

    import httpx

    from benchmarks.extraction_load import measure

    ids = {key: str(uuid4()) for key in ("org", "user", "run")}
    event = dict(id=2, type="review_waiting", run_id=ids["run"], payload={"count": 100})
    ids["resume"] = (1, dict(id=2, event_type="review_waiting", projected=event))
    transmitted = dict(event, payload={"count": 99}) if kind == "wrong_payload" else event
    frame = ": connected\n\n"
    if kind != "comment_only":
        frame += (
            f"id: {3 if kind == 'wrong_id' else 2}\nevent: review_waiting\n"
            f"data: {json.dumps(transmitted)}\n\n"
        )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429 if kind == "error" else 200, text=frame)
        ),
        base_url="http://localhost",
    )
    monkeypatch.setattr("benchmarks.extraction_load.httpx.Client", lambda **kwargs: client)
    result = measure("waiting_reconnect", ids, "http://localhost", threading.Barrier(1))
    assert result["verified"] == (kind == "correct")
    assert bool(result["error"]) == (kind != "correct")


def test_real_preflight_cli_writes_metadata_and_all_verified_operations(tmp_path):
    """Exercise argument parsing, subprocess metadata, owned HTTP and durable PG."""
    import os
    import signal
    import socket
    import subprocess
    import sys
    from pathlib import Path
    from uuid import uuid4

    import psycopg

    from migrate import main as migrate

    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        if os.environ.get("FEL_REQUIRE_DB") == "1":
            pytest.fail("FEL_REQUIRE_DB requires TEST_DATABASE_URL for CLI acceptance")
        pytest.skip("TEST_DATABASE_URL not configured")
    connection = psycopg.conninfo.conninfo_to_dict(base)
    database = "fel_load_cli_" + uuid4().hex
    connection["dbname"] = database
    url = psycopg.conninfo.make_conninfo(**connection)
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(database)))
    try:
        assert migrate(["--database-url", url]) == 0
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        root = Path(__file__).resolve().parents[3]
        output = tmp_path / "artifacts"
        env = {
            **os.environ,
            "FEL_DATABASE_URL": url,
            "FEL_STORAGE_DIR": str(tmp_path / "storage"),
            "FEL_AUTH_MODE": "mock",
            "FEL_ALLOW_MOCK_LLM": "1",
            "FEL_WORKER_DB_ROLE": "fel_worker",
            "PYTHONPATH": os.pathsep.join(
                str(root / path)
                for path in (
                    "apps/api",
                    "evals",
                    "workers/src",
                    "packages/providers",
                    "packages/ontology",
                    "packages/retrieval",
                    "packages/retrieval-evals",
                )
            ),
        }
        with subprocess.Popen(
            [
                sys.executable,
                "-m",
                "benchmarks.extraction_load",
                "--preflight-only",
                "--port",
                str(port),
                "--output",
                str(output),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            try:
                process.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                # The parent may already have exited while its child holds the
                # pipes open. Terminate the whole owned group before DB cleanup.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=10)
                raise
            assert process.returncode == 1  # Preflight alone cannot pass load acceptance.
        import json

        metadata = json.loads((output / "metadata.json").read_text())
        rows = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
        result = json.loads((output / "report.json").read_text())
        assert len(metadata["commit"]) == 40
        assert len(metadata["tree"]) == 40
        assert metadata["proposal_count"] == 100
        assert len(rows) == 4
        assert {row["operation"] for row in rows} == set(OPERATIONS)
        assert all(
            row["phase"] == "preflight" and row["verified"] and not row["error"] for row in rows
        )
        assert result["setup_and_warmup_passed"] is True
        assert result["execution_error"] is None
        assert result["passed"] is False
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(database)
                )
            )
