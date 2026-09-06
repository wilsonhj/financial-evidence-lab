"""The packaged contract schema must equal the repository's, byte for byte (#192).

``validate/schema.py`` reads the frozen extraction-payload schema out of package
data so it resolves from an installed wheel — the loader used to walk parent
directories for ``packages/contracts/schemas/…``, which finds nothing in
``site-packages`` and raises ``FileNotFoundError`` on the first payload a
deployed worker validates.

Vendoring buys that at the price of a second copy, and a second copy that can
drift is worse than the bug it fixed: the worker would silently validate against
a stale contract while ``packages/contracts`` published the current one. This
test is the price being paid. It fails CI the moment the two differ, so the
mirror can only ever be updated in the same change as the contract.

``packages/contracts/schemas/extraction-payload.schema.json`` remains
authoritative. When it changes, copy it to
``workers/src/fel_workers/extraction/contracts/`` in the same PR.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path

import pytest

from fel_workers.extraction.contracts import EXTRACTION_PAYLOAD_SCHEMA_FILENAME
from fel_workers.extraction.validate.schema import load_extraction_payload_schema

_REPO_SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "schemas"
    / EXTRACTION_PAYLOAD_SCHEMA_FILENAME
)


def _packaged_bytes() -> bytes:
    return (
        resources.files("fel_workers.extraction.contracts")
        .joinpath(EXTRACTION_PAYLOAD_SCHEMA_FILENAME)
        .read_bytes()
    )


def test_packaged_schema_is_byte_identical_to_the_repository_copy() -> None:
    if not _REPO_SCHEMA.is_file():
        pytest.skip(f"repository contract copy not present at {_REPO_SCHEMA}")
    repo = _REPO_SCHEMA.read_bytes()
    packaged = _packaged_bytes()
    assert hashlib.sha256(packaged).hexdigest() == hashlib.sha256(repo).hexdigest(), (
        "the vendored extraction-payload schema has drifted from "
        f"{_REPO_SCHEMA}. Copy the repository file over "
        "workers/src/fel_workers/extraction/contracts/ in the same change."
    )


def test_loader_reads_package_data_and_not_the_repository_tree() -> None:
    """The loader must not depend on a repo layout above the package.

    Asserted structurally rather than by mocking the filesystem: the schema the
    loader returns has to be the parsed form of the PACKAGED bytes.
    """
    assert load_extraction_payload_schema() == json.loads(_packaged_bytes())


def test_loaded_schema_is_usable() -> None:
    schema = load_extraction_payload_schema()
    assert isinstance(schema, dict)
    assert "$defs" in schema
    assert {"kpi", "revenueDriver"} <= set(schema["$defs"])
