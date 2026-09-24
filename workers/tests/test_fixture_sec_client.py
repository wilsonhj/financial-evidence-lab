"""Pinned local SEC transport: exact bytes, no fallback and fail-closed assets."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from fel_workers.ingestion.fixture_sec_client import FixtureSecClient

URL = "https://www.sec.gov/Archives/fixture.htm"
RAW = b"<html>\r\nexact \xc3\xa9 bytes\x00</html>"


def write_fixture(root: Path) -> dict[str, object]:
    (root / "filing.htm").write_bytes(RAW)
    submissions = b'{"filings": {"recent": {}}}'
    (root / "submissions.json").write_bytes(submissions)
    manifest: dict[str, object] = {
        "schema_version": "sec-fixture-transport/v1",
        "documents": [
            {"url": URL, "path": "filing.htm", "sha256": hashlib.sha256(RAW).hexdigest()}
        ],
        "submissions": [
            {
                "cik": "0000123456",
                "path": "submissions.json",
                "sha256": hashlib.sha256(submissions).hexdigest(),
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_exact_bytes_and_normalized_submissions_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_fixture(tmp_path)

    def no_network(*args: object, **kwargs: object) -> None:
        pytest.fail("fixture transport attempted network")

    monkeypatch.setattr(socket, "socket", no_network)
    client = FixtureSecClient(tmp_path)
    assert client.fetch_document(URL) == RAW
    assert client.submissions("123456") == {"filings": {"recent": {}}}
    assert client.submissions("CIK0000123456") == client.submissions("123456")
    with pytest.raises(ValueError, match="not in fixture manifest"):
        client.fetch_document(URL + "?not-listed")
    with pytest.raises(ValueError, match="not in fixture manifest"):
        client.submissions("1")


@pytest.mark.parametrize(
    "mutation", ["version", "hash", "traversal", "absolute", "duplicate", "shape", "unknown"]
)
def test_bad_manifest_fails_closed(tmp_path: Path, mutation: str) -> None:
    manifest = write_fixture(tmp_path)
    rows = manifest["documents"]
    assert isinstance(rows, list)
    if mutation == "version":
        manifest["schema_version"] = "unknown"
    elif mutation == "hash":
        rows[0]["sha256"] = "0" * 64
    elif mutation == "traversal":
        rows[0]["path"] = "../filing.htm"
    elif mutation == "absolute":
        rows[0]["path"] = str(tmp_path / "filing.htm")
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "shape":
        manifest["documents"] = {}
    else:
        rows[0]["unrecognized"] = "value"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        FixtureSecClient(tmp_path)


def test_file_tampering_after_binding_is_detected(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    client = FixtureSecClient(tmp_path)
    (tmp_path / "filing.htm").write_bytes(b"changed")
    with pytest.raises(ValueError, match="sha256"):
        client.fetch_document(URL)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    write_fixture(root)
    outside = tmp_path / "outside"
    outside.write_bytes(RAW)
    (root / "filing.htm").unlink()
    (root / "filing.htm").symlink_to(outside)
    with pytest.raises(ValueError, match="path"):
        FixtureSecClient(root)


def test_submissions_must_be_json_object(tmp_path: Path) -> None:
    manifest = write_fixture(tmp_path)
    raw = b"[]"
    (tmp_path / "submissions.json").write_bytes(raw)
    rows = manifest["submissions"]
    assert isinstance(rows, list)
    rows[0]["sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="object"):
        FixtureSecClient(tmp_path).submissions("123456")


@pytest.mark.parametrize(
    "raw", [b"[]", b"{", b"{}\xff", b'{"schema_version":1,"schema_version":2}']
)
def test_malformed_manifest_json_rejected(tmp_path: Path, raw: bytes) -> None:
    (tmp_path / "manifest.json").write_bytes(raw)
    with pytest.raises(ValueError, match="object"):
        FixtureSecClient(tmp_path)


def test_missing_asset_rejected_at_binding(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    (tmp_path / "filing.htm").unlink()
    with pytest.raises(ValueError, match="readable"):
        FixtureSecClient(tmp_path)


@pytest.mark.parametrize(
    "field,value", [("sha256", "xyz"), ("url", None), ("path", ""), ("cik", "not-a-cik")]
)
def test_invalid_entry_fields_rejected(tmp_path: Path, field: str, value: object) -> None:
    manifest = write_fixture(tmp_path)
    rows = manifest["submissions" if field == "cik" else "documents"]
    assert isinstance(rows, list)
    rows[0][field] = value
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        FixtureSecClient(tmp_path)


def test_duplicate_normalized_cik_rejected(tmp_path: Path) -> None:
    manifest = write_fixture(tmp_path)
    rows = manifest["submissions"]
    assert isinstance(rows, list)
    rows.append({**rows[0], "cik": "123456"})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate"):
        FixtureSecClient(tmp_path)


def test_submissions_tampering_and_independent_results(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    client = FixtureSecClient(tmp_path)
    first = client.submissions("123456")
    first.clear()
    assert client.submissions("123456") == {"filings": {"recent": {}}}
    (tmp_path / "submissions.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="sha256"):
        client.submissions("123456")
