"""Corpus-QA evaluation harness (T0112).

Drives the REAL discovery -> fetch -> ingest pipeline over the canonical
benchmark issuer cohort and records corpus-quality metrics to a versioned
JSON report. Two modes:

- ``synthetic`` (default; no egress): a deterministic mock ``SecClient``
  serves committed synthetic fixture templates — the pipeline, queue,
  quarantine, and metrics code paths are all real, the bytes are not.
- ``live`` (requires SEC egress + fair-access compliance): the frozen
  ``LiveSecClient`` fetches real EDGAR filings for the same cohort.

See ``evals/reports/corpus-qa/SCHEMA.md`` for the report schema and the
exact commands.
"""
