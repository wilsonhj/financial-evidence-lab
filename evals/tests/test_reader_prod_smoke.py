"""Fail-closed preparation and reversible fault proofs for the real reader smoke."""

import hashlib
import json
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from harness.reader_prod_smoke import FIXTURES, blob_fault, checked_outcomes, require_target, setup
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
