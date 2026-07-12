"""Unit test for the deterministic exact-match grader."""

from __future__ import annotations

from graders.exact_match import exact_match


def test_exact_match_scoring() -> None:
    assert exact_match("Revenue", " Revenue ") == 1.0
    assert exact_match("Revenue", "Bookings") == 0.0
