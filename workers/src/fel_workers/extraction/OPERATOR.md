"""Operator notes for extraction workers.

Queue: ``extraction`` (do not mix with default ``ingestion`` in production).
Job kind: ``extraction_run`` with payload containing run pin fields and optional
inline ``spans`` for mock/tests.

Budgets default to ADR-0007 caps. Telemetry is redacted — never logs prompts or
filing text. All proposals enter ``needs_review``; there is no auto-approve path.
"""
