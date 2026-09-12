"""Sibling-database provisioning for extraction API fixtures.

CI creates and migrates only ``fel_test``. Extraction suites must not share
that database: durable ``extraction_runs`` rows block later
``corpus_versions`` cleanup. The ``extraction_url`` fixture therefore owns
``<db>_extraction`` — create, migrate, and current-schema check — the same
way worker crash-resume tests do. A path rewrite alone fails in CI with
``database "fel_test_extraction" does not exist``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import psycopg


def test_extraction_url_creates_and_migrates_current_sibling(extraction_url: str) -> None:
    parsed = urlsplit(extraction_url)
    assert parsed.path.endswith("_extraction"), extraction_url
    with psycopg.connect(extraction_url) as conn:
        runs = conn.execute("SELECT to_regclass('public.extraction_runs')").fetchone()
        assert runs is not None and runs[0] == "extraction_runs"
        context = conn.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = 'approved_extraction_versions'
                   AND column_name = 'validation_context'
            )
            """).fetchone()
        assert context is not None and context[0] is True
        occurrence = conn.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = 'extraction_conflicts'
                   AND column_name = 'occurrence_run_id'
            )
            """).fetchone()
        assert occurrence is not None and occurrence[0] is True
