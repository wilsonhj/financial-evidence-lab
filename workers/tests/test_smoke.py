"""Smoke test asserting the worker package skeleton is importable."""

from __future__ import annotations

from fel_workers import WORKSTREAMS


def test_workstreams_declared() -> None:
    assert WORKSTREAMS == ("ingestion", "extraction", "forecasting")
