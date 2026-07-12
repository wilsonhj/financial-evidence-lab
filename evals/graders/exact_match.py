"""Deterministic exact-match grader.

The scaffold ships one trivially deterministic grader so the CI evaluation
gate (SPEC.md Section 20.2) has an executable target before the adjudicated
benchmark datasets (T0214) land.
"""

from __future__ import annotations


def exact_match(expected: str, actual: str) -> float:
    """Return 1.0 when whitespace-normalized strings match exactly, else 0.0."""
    return 1.0 if expected.strip() == actual.strip() else 0.0
