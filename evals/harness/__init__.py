"""Evaluation harnesses.

- ``corpus_qa`` (T0112): REAL discovery -> fetch -> ingest over the
  benchmark issuer cohort. Synthetic (default) or live SEC modes.
- ``reader_cross_stack`` (issue #96): ADR-0005 composite reader
  mock-first verification; optional FastAPI stack path via
  ``TEST_DATABASE_URL``.

See ``evals/reports/corpus-qa/SCHEMA.md`` and
``evals/datasets/reader-cross-stack/README.md``.
"""
