"""Deterministic renderers for committed evaluation reports.

- ``corpus_qa_render`` (issue #151): turns one ``corpus-qa-report/v1`` (or
  its ``corpus-qa-failure/v1`` sibling) JSON artifact into a Markdown
  summary and a hand-written SVG chart. Stdlib-only, byte-deterministic,
  no database and no network.

See ``evals/reporting/README.md`` and the input schema at
``evals/reports/corpus-qa/SCHEMA.md``.
"""
