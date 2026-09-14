"""Fail-closed preparation and reversible fault proofs for the real reader smoke."""

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from harness.reader_prod_smoke import FIXTURES, blob_fault, checked_outcomes, require_target, setup
from harness.reader_prod_smoke_service import WATCHDOG_HEAL_DELAY_S, should_auto_heal
from migrate import main as migrate


def test_committed_transport_bytes_and_real_parser():
    from fel_workers.ingestion.parser import parse_filing

    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["schema_version"] == "sec-fixture-transport/v1"
    assert manifest["submissions"] == []
    assert len(manifest["documents"]) == 4
    hashes = set()
    for doc in manifest["documents"]:
        raw = (FIXTURES / doc["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == doc["sha256"]
        hashes.add(doc["sha256"])
        parsed = parse_filing(raw)
        assert len(parsed.sections) >= 3
        assert any(s.heading == "Item 2. Management discussion" for s in parsed.sections)
    assert len(hashes) == 4


@pytest.mark.parametrize("target", ["", "x", "../target", "production;other"])
def test_invalid_target_rejected(monkeypatch, target):
    monkeypatch.setenv("FEL_READER_SMOKE_TARGET", target)
    with pytest.raises(ValueError):
        require_target(target)


def test_target_must_be_explicit_twice(monkeypatch):
    monkeypatch.delenv("FEL_READER_SMOKE_TARGET", raising=False)
    with pytest.raises(ValueError):
        require_target("local-reader")
    monkeypatch.setenv("FEL_READER_SMOKE_TARGET", "local-reader")
    require_target("local-reader")


def test_failed_job_and_missing_ingestion_version_rejected():
    jobs = [{"status": "succeeded"} for _ in range(4)]
    ingestions = [{"status": "succeeded", "document_version_id": str(uuid4())} for _ in range(4)]
    jobs[0]["status"] = "failed"
    with pytest.raises(RuntimeError, match="queue jobs"):
        checked_outcomes(jobs, ingestions)
    jobs[0]["status"] = "succeeded"
    ingestions[0]["document_version_id"] = None
    with pytest.raises(RuntimeError, match="ingestions"):
        checked_outcomes(jobs, ingestions)


@pytest.mark.parametrize("status", ["failed", "queued", "running", "quarantined"])
def test_worker_zero_is_not_ingestion_acceptance(status):
    jobs = [{"status": "succeeded"} for _ in range(4)]
    ingestions = [{"status": "succeeded", "document_version_id": str(uuid4())} for _ in range(4)]
    checked_outcomes(jobs, ingestions)
    ingestions[2]["status"] = status
    with pytest.raises(RuntimeError, match="ingestions"):
        checked_outcomes(jobs, ingestions)
    with pytest.raises(RuntimeError, match="queue jobs"):
        checked_outcomes(jobs[:-1], ingestions)


def test_blob_fault_changes_verified_range_and_restores(monkeypatch, tmp_path):
    target = "local-reader"
    monkeypatch.setenv("FEL_READER_SMOKE_TARGET", target)
    (tmp_path / ".reader-smoke-target").write_text(target)
    raw = "Préface. Exact quote.".encode()
    path = tmp_path / "canonical"
    path.write_bytes(raw)
    manifest = {
        "target": target,
        "documents": {
            "amendment2": {
                "canonical_key": "canonical",
                "canonical_sha256": hashlib.sha256(raw).hexdigest(),
                "start_char": 9,
            }
        },
    }
    blob_fault(manifest, tmp_path, target, restore=False)
    assert path.read_text() == "Préface. Xxact quote."
    with pytest.raises(ValueError, match="already changed"):
        blob_fault(manifest, tmp_path, target, restore=False)
    blob_fault(manifest, tmp_path, target, restore=True)
    assert path.read_bytes() == raw
    manifest["documents"]["amendment2"]["canonical_key"] = "../outside"
    with pytest.raises(ValueError, match="inside dedicated storage"):
        blob_fault(manifest, tmp_path, target, restore=False)


def test_invalid_restoration_never_overwrites_blob(monkeypatch, tmp_path):
    monkeypatch.setenv("FEL_READER_SMOKE_TARGET", "local-reader")
    (tmp_path / ".reader-smoke-target").write_text("local-reader")
    (tmp_path / "canonical").write_bytes(b"changed")
    (tmp_path / ".reader-smoke-original").write_bytes(b"wrong")
    manifest = {
        "target": "local-reader",
        "documents": {
            "amendment2": {
                "canonical_key": "canonical",
                "canonical_sha256": hashlib.sha256(b"original").hexdigest(),
            }
        },
    }
    with pytest.raises(ValueError, match="invalid restoration"):
        blob_fault(manifest, tmp_path, "local-reader", restore=True)
    assert (tmp_path / "canonical").read_bytes() == b"changed"


@pytest.fixture
def database():
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        if os.environ.get("FEL_REQUIRE_DB") == "1":
            pytest.fail("FEL_REQUIRE_DB=1 requires TEST_DATABASE_URL")
        pytest.skip("TEST_DATABASE_URL not configured")
    name = "reader_smoke_" + uuid4().hex
    url = urlunsplit(urlsplit(base)._replace(path="/" + name))
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        assert migrate(["--database-url", url]) == 0
        yield url
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_real_worker_setup_and_blob_recovery(database, monkeypatch, tmp_path):
    monkeypatch.setenv("FEL_READER_SMOKE_TARGET", "local-reader")
    # The child is the production CLI, not an in-process mock dispatcher.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(str(p) for p in __import__("sys").path))
    manifest = setup(database, tmp_path, "local-reader")
    assert len(manifest["documents"]) == 4
    assert manifest["corpus"] != manifest["pinned_corpus"]
    assert manifest["denied_user"] != manifest["user"]
    assert "token" not in json.dumps(manifest)
    for document in manifest["documents"].values():
        assert document["start_char"] > 0
        assert (
            "sha256:" + hashlib.sha256(document["quote"].encode()).hexdigest()
            == document["text_hash"]
        )
    blob_fault(manifest, tmp_path, "local-reader", restore=False)
    blob_fault(manifest, tmp_path, "local-reader", restore=True)
    with pytest.raises(ValueError, match="empty evidence database"):
        setup(database, tmp_path, "local-reader")


@pytest.mark.parametrize(
    "module,action",
    [
        ("os", "stop"),
        ("evals.harness.reader_prod_smoke", "setup"),
        ("evals.harness.reader_prod_smoke_service", "serve"),
        ("evals.harness.reader_prod_smoke", "corrupt; rm -rf /"),
    ],
)
def test_remote_rejects_non_allowlisted_operations(module, action, tmp_path):
    from harness.reader_prod_smoke_remote import parse_operation

    config = {"TARGET": "dedicated-smoke", "MANIFEST": str(tmp_path / "manifest")}
    args = [
        "-m",
        module,
        action,
        "--manifest",
        config["MANIFEST"],
        "--dedicated-target",
        config["TARGET"],
    ]
    with pytest.raises(ValueError, match="allowlisted"):
        parse_operation(args, config)


def test_remote_operation_binds_both_target_and_local_manifest(tmp_path):
    from harness.reader_prod_smoke_remote import parse_operation

    config = {"TARGET": "dedicated-smoke", "MANIFEST": str(tmp_path / "manifest")}
    args = [
        "-m",
        "evals.harness.reader_prod_smoke",
        "corrupt",
        "--manifest",
        config["MANIFEST"],
        "--dedicated-target",
        config["TARGET"],
    ]
    assert parse_operation(args, config) == ("evals.harness.reader_prod_smoke", "corrupt")
    args[6] = "other-target"
    with pytest.raises(ValueError, match="target mismatch"):
        parse_operation(args, config)
    args[6] = config["TARGET"]
    args[4] = str(tmp_path / "different")
    with pytest.raises(ValueError, match="manifest path"):
        parse_operation(args, config)
    with pytest.raises(ValueError, match="interface"):
        parse_operation(["anything"], config)


def test_remote_shell_arguments_never_become_commands(tmp_path):
    import subprocess
    import sys

    from harness.reader_prod_smoke_remote import remote_command

    directory = tmp_path / "spaces ' and $(touch SHOULD_NOT_EXIST)"
    directory.mkdir()
    payload = "quote '; touch SHOULD_NOT_EXIST; $(echo injected) `echo nope`"
    command = remote_command(
        str(directory),
        sys.executable,
        [
            "-c",
            "import json,sys; print(json.dumps(sys.argv[1:]))",
            payload,
        ],
    )
    result = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [payload]
    assert not list(tmp_path.rglob("SHOULD_NOT_EXIST"))


def test_remote_ssh_failure_does_not_echo_secret_output(monkeypatch):
    from types import SimpleNamespace

    from harness import reader_prod_smoke_remote as remote

    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"secret stdout",
            stderr=b"secret stderr",
        ),
    )
    with pytest.raises(RuntimeError) as error:
        remote.ssh({"SSH_KEY": "key", "KNOWN_HOSTS": "hosts"}, str(uuid4()), "fixed")
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("wrong", ["revision", "target", "domain"])
def test_remote_preflight_fails_before_mutation_for_wrong_deployment(tmp_path, wrong):
    import subprocess
    import sys

    from harness.reader_prod_smoke_remote import API_PROGRAM

    environment = os.environ.copy()
    environment.update(
        RAILWAY_GIT_COMMIT_SHA="a" * 40,
        FEL_READER_SMOKE_TARGET="dedicated-smoke",
        RAILWAY_PUBLIC_DOMAIN="api.example.test",
        PYTHONOPTIMIZE="1",
    )
    if wrong == "revision":
        environment["RAILWAY_GIT_COMMIT_SHA"] = "b" * 40
    elif wrong == "target":
        environment["FEL_READER_SMOKE_TARGET"] = "other-target"
    else:
        environment["RAILWAY_PUBLIC_DOMAIN"] = "wrong.example.test"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            API_PROGRAM,
            "a" * 40,
            "dedicated-smoke",
            str(tmp_path / "manifest-does-not-exist"),
            "https://api.example.test",
            "",
            "inspect",
        ],
        env=environment,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"AssertionError" in result.stderr
    assert b"FileNotFoundError" not in result.stderr


def test_service_control_never_exposes_a_partial_command(monkeypatch, tmp_path):
    import io

    from harness.reader_prod_smoke_service import write_control

    control = tmp_path / "manifest.api-control"
    control.write_text("start")
    original_open = io.open
    observations = []

    def observe_after_open(file, mode="r", *args, **kwargs):
        opened = original_open(file, mode, *args, **kwargs)
        if "w" in mode:
            # Model a scheduler switch immediately after a writer opens its
            # destination. An in-place write has already truncated it here.
            with original_open(control) as reader:
                observations.append(reader.read())
        return opened

    monkeypatch.setattr(io, "open", observe_after_open)
    write_control(control, "stop")
    assert observations and all(value == "start" for value in observations)
    assert control.read_text() == "stop"
    assert list(tmp_path.iterdir()) == [control]


def test_service_control_failed_replacement_preserves_previous_command(monkeypatch, tmp_path):
    from pathlib import Path

    from harness.reader_prod_smoke_service import write_control

    control = tmp_path / "manifest.api-control"
    control.write_text("start")

    def fail_replace(source, destination):
        raise OSError("replacement refused")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement refused"):
        write_control(control, "stop")
    assert control.read_text() == "start"
    assert list(tmp_path.iterdir()) == [control]


def test_artifact_sanitizer_preserves_public_evidence(tmp_path):
    import zipfile

    from harness.reader_prod_smoke_remote import sanitize_artifacts

    artifacts = tmp_path / ".reader-smoke"
    artifacts.mkdir()
    manifest = artifacts / "manifest.json"
    manifest.write_text('{"target":"dedicated-smoke","documents":[]}')
    trace = artifacts / "browser-trace.zip"
    with zipfile.ZipFile(trace, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("trace.trace", '{"url":"https://web.example.test/reader/123"}')
        archive.writestr("resources/screenshot.png", b"public image bytes")
    before = {p.name: p.read_bytes() for p in artifacts.iterdir()}
    sanitize_artifacts([artifacts, tmp_path / "absent-results"])
    assert {p.name: p.read_bytes() for p in artifacts.iterdir()} == before


@pytest.mark.parametrize("placement", ["plain", "zip-entry", "zip-name", "chunk-boundary"])
def test_artifact_sanitizer_removes_bearer_leaks_without_echoing(tmp_path, placement):
    import zipfile

    from harness.reader_prod_smoke_remote import sanitize_artifacts

    token = "mock.synthetic_owner_credential"
    safe = tmp_path / "manifest.json"
    safe.write_text('{"target":"dedicated-smoke"}')
    leaking = tmp_path / ("trace.zip" if placement.startswith("zip") else "result.json")
    if placement.startswith("zip"):
        with zipfile.ZipFile(leaking, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                token if placement == "zip-name" else "trace.trace",
                "safe body" if placement == "zip-name" else "Authorization: Bearer " + token,
            )
    else:
        prefix = "x" * 65533 if placement == "chunk-boundary" else "Authorization: Bearer "
        leaking.write_text(prefix + token)
    with pytest.raises(RuntimeError) as error:
        sanitize_artifacts([tmp_path])
    assert token not in str(error.value)
    assert "Bearer" not in str(error.value)
    assert not leaking.exists()
    assert safe.exists()


def test_artifact_sanitizer_rejects_unreadable_zip_and_scans_every_file(tmp_path):
    from harness.reader_prod_smoke_remote import sanitize_artifacts

    (tmp_path / "broken.zip").write_bytes(b"not a readable archive")
    (tmp_path / "first.json").write_text("mock.synthetic_first")
    (tmp_path / "second.json").write_text("mock.synthetic_second")
    with pytest.raises(RuntimeError):
        sanitize_artifacts([tmp_path])
    assert list(tmp_path.iterdir()) == []


def test_recovery_attempts_blob_restore_when_api_restart_fails(monkeypatch, tmp_path):
    import subprocess
    import sys
    from types import SimpleNamespace

    from harness.reader_prod_smoke_remote import API_PROGRAM

    target = "dedicated-smoke"
    manifest = {
        key: "synthetic"
        for key in (
            "schema_version",
            "target",
            "org",
            "user",
            "denied_user",
            "workspace",
            "entity",
            "as_of",
            "corpus",
            "pinned_corpus",
            "documents",
            "jobs",
        )
    }
    manifest.update(schema_version="reader-prod-smoke/v1", target=target)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    (tmp_path / ".reader-smoke-target").write_text(target)
    (tmp_path / ".reader-smoke-original").write_bytes(b"synthetic backup")
    for name, value in {
        "RAILWAY_PUBLIC_DOMAIN": "api.example.test",
        "RAILWAY_GIT_COMMIT_SHA": "a" * 40,
        "FEL_READER_SMOKE_TARGET": target,
        "FEL_READER_SMOKE_SERVICE_HOSTED": "1",
        "FEL_AUTH_MODE": "mock",
        "FEL_STORAGE_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remote",
            "a" * 40,
            target,
            str(path),
            "https://api.example.test",
            "",
            "recover",
        ],
    )
    actions = []

    def recovery_process(argv, **kwargs):
        action = argv[3]
        actions.append(action)
        code = 1 if action == "start" else 0
        if code and kwargs.get("check"):
            raise subprocess.CalledProcessError(code, argv)
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(subprocess, "run", recovery_process)
    with pytest.raises(RuntimeError, match="recovery was incomplete"):
        exec(API_PROGRAM, {})
    assert actions == ["start", "restore"]


def test_watchdog_heal_delay_outlasts_playwright_outage_budget():
    root = Path(__file__).resolve().parents[2]
    config = (root / "apps/web/playwright.reader-prod-smoke.config.ts").read_text()
    match = re.search(r"^  timeout: ([0-9_]+),$", config, flags=re.MULTILINE)
    assert match is not None
    playwright_test_timeout_s = int(match.group(1).replace("_", "")) / 1000
    assert WATCHDOG_HEAL_DELAY_S > playwright_test_timeout_s
    assert not should_auto_heal(stopped_at=0.0, now=60.0)
    assert not should_auto_heal(stopped_at=0.0, now=playwright_test_timeout_s)
    assert not should_auto_heal(stopped_at=0.0, now=WATCHDOG_HEAL_DELAY_S - 0.1)
    assert should_auto_heal(stopped_at=0.0, now=WATCHDOG_HEAL_DELAY_S)
    assert not should_auto_heal(stopped_at=None, now=WATCHDOG_HEAL_DELAY_S)
    source = (root / "evals/harness/reader_prod_smoke_service.py").read_text()
    assert "if should_auto_heal(stopped_at, time.monotonic()):" in source
