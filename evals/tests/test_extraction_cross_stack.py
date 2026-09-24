"""The acceptance provider changes source identity, never financial fixture data."""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.auth import make_mock_token
from app.db import pool_for
from app.main import app
from fel_providers.interfaces import StructuredGenerationRequest
from fel_providers.mocks import MockStructuredLLMProvider
from harness.extraction_cross_stack import ScopedMock, main, verify
from migrate import main as migrate


@pytest.mark.parametrize("schema_name", ["classifier", "candidates", "kpi"])
def test_scoped_model_changes_only_identity_and_preserves_financial_values(schema_name):
    manifest = {key: str(uuid4()) for key in ("span", "version", "entity")}
    request = StructuredGenerationRequest(
        messages=[{"role": "user", "content": "Synthetic acceptance evidence"}],
        json_schema={},
        schema_name=schema_name,
        schema_version="acceptance/v1",
        max_output_tokens=1000,
    )
    baseline = MockStructuredLLMProvider().generate_structured(request)
    actual = ScopedMock(manifest).generate_structured(request)
    identities = {
        "source_span_id": manifest["span"],
        "document_version_id": manifest["version"],
        "entity_id": manifest["entity"],
    }

    def compare(left, right):
        if isinstance(left, dict):
            assert left.keys() == right.keys()
            for key, value in left.items():
                if key in identities:
                    assert right[key] == identities[key]
                else:
                    compare(value, right[key])
        elif isinstance(left, list):
            assert len(left) == len(right)
            for before, after in zip(left, right, strict=True):
                compare(before, after)
        else:
            assert left == right

    compare(baseline.parsed, actual.parsed)
    assert actual.input_tokens == baseline.input_tokens
    assert actual.output_tokens == baseline.output_tokens
    assert actual.estimated_cost_usd == baseline.estimated_cost_usd


@pytest.fixture
def acceptance_database(monkeypatch, tmp_path):
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        if os.environ.get("FEL_REQUIRE_DB") == "1":
            pytest.fail("FEL_REQUIRE_DB=1 requires TEST_DATABASE_URL for acceptance regression")
        pytest.skip("TEST_DATABASE_URL not configured")
    name = "fel_extraction_acceptance_" + uuid4().hex
    parsed = urlsplit(base)
    url = urlunsplit(parsed._replace(path="/" + name))
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        assert migrate(["--database-url", url]) == 0
        monkeypatch.setenv("FEL_DATABASE_URL", url)
        monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path / "storage"))
        monkeypatch.setenv("FEL_DEPLOYMENT_MODE", "synthetic-http")
        monkeypatch.setenv("FEL_SYNTHETIC_HTTP_TARGET", "extraction-cross-stack-tests")
        monkeypatch.delenv("PGHOSTADDR", raising=False)
        monkeypatch.delenv("PGSERVICE", raising=False)
        monkeypatch.setenv("FEL_AUTH_MODE", "mock")
        monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
        monkeypatch.setenv("FEL_WORKER_DB_ROLE", "fel_worker")
        yield url
    finally:
        pool_for(url).close()
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_harness_seeds_source_runs_worker_and_verifies_real_immutable_rows(
    acceptance_database, monkeypatch, tmp_path
):
    """Exercise harness internals with PG; separate Playwright uses real sockets."""
    manifest_path = tmp_path / "manifest.json"

    def command(action, *args):
        monkeypatch.setattr(
            sys, "argv", ["acceptance", action, "--manifest", str(manifest_path), *args]
        )
        main()

    command("seed")
    manifest = json.loads(manifest_path.read_text())
    headers = {
        "Authorization": f"Bearer {make_mock_token(manifest['org'], manifest['user'], 'owner')}",
    }
    client = TestClient(app)
    created = client.post(
        f"/v1/workspaces/{manifest['workspace']}/extraction-runs",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "entity_id": manifest["entity"],
            "modes": ["kpi"],
            "source_span_ids": [manifest["span"]],
            "corpus_version_id": manifest["corpus"],
            "as_of": "2026-12-31T00:00:00Z",
        },
    )
    assert created.status_code == 202, created.text
    run = created.json()["id"]
    command("work")
    with pytest.raises(RuntimeError, match="exactly one successfully processed"):
        command("work")
    proposals = client.get(f"/v1/workspaces/{manifest['workspace']}/extractions", headers=headers)
    assert proposals.status_code == 200, proposals.text
    assert len(proposals.json()["items"]) == 1
    proposal = proposals.json()["items"][0]
    result = client.post(
        "/v1/extractions/review",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "action": "accept",
            "extraction_ids": [proposal["id"]],
            "expected_versions": {proposal["id"]: proposal["version"]},
            "reason": "Canonical evidence verified",
        },
    )
    assert result.status_code == 200, result.text
    record = result.json()["approved_record_ids"][0]
    with pytest.raises(RuntimeError, match="one immutable correction"):
        verify(acceptance_database, manifest, run, record)
    old = client.get(f"/v1/approved-extractions/{record}", headers=headers)
    corrected = client.post(
        f"/v1/approved-extractions/{record}/corrections",
        headers={**headers, "Idempotency-Key": str(uuid4()), "If-Match": old.headers["etag"]},
        json={
            "reason": "Second review of pinned evidence",
            "payload": old.json()["payload"],
            "evidence": old.json()["evidence"],
        },
    )
    assert corrected.status_code == 201, corrected.text
    command("verify", "--run", run, "--record", record)
    previous = client.get(
        f"/v1/approved-extractions/{record}/versions/{old.json()['version_id']}",
        headers=headers,
    )
    assert previous.json() == old.json()
    with pytest.raises(RuntimeError, match="actual source span"):
        verify(acceptance_database, {**manifest, "span": str(uuid4())}, run, record)
