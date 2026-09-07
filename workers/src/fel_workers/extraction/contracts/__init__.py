"""Vendored copies of the frozen contract schemas the worker reads at runtime.

The repo copy under ``packages/contracts/schemas/`` stays AUTHORITATIVE: these
files are a byte-for-byte mirror of it, never an edit of it, and
``workers/tests/extraction/test_vendored_contract_schema.py`` fails CI if the
two ever diverge. Change the contract there, then copy it here in the same PR.

Why the mirror exists (issue #192): the loader used to find the schema by
walking parent directories for ``packages/contracts/schemas/…``. That works in a
git checkout and nowhere else. Installed as a wheel — which is how the worker
actually ships — ``fel_workers`` lives in ``site-packages`` with no repository
above it, so the walk reaches the filesystem root and raises
``FileNotFoundError`` at the first payload validated. The failure is at runtime,
on the first real job, not at import or build time.

Loaded with :mod:`importlib.resources`, so it works from a directory, a wheel or
a zipimport alike.
"""

from __future__ import annotations

EXTRACTION_PAYLOAD_SCHEMA_FILENAME = "extraction-payload.schema.json"

__all__ = ["EXTRACTION_PAYLOAD_SCHEMA_FILENAME"]
