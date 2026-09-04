"""Newest-first list bounding: omitted limit fails closed, explicit limit pages."""

from __future__ import annotations

import pytest

from app.listing import ListTooLarge, newest_page


def test_omitted_limit_returns_every_row_when_under_the_default() -> None:
    rows = ["c", "b", "a"]  # already newest-first
    assert newest_page(rows, requested_limit=None, default_limit=50, resource="documents") == rows


def test_omitted_limit_refuses_to_silently_drop_the_newest() -> None:
    """The frozen contract documents an unbounded list. A default cap that
    keeps the *oldest* rows and drops the newest is an evidence leak; failing
    closed is the only honest default until cursor pagination lands."""
    rows = [f"n{i}" for i in range(51)]  # 51 newest-first rows (SQL LIMIT default+1)
    with pytest.raises(ListTooLarge) as excinfo:
        newest_page(rows, requested_limit=None, default_limit=50, resource="documents")
    assert excinfo.value.resource == "documents"
    assert excinfo.value.limit == 50


def test_explicit_limit_returns_the_newest_page() -> None:
    rows = ["newest", "middle", "oldest"]
    assert newest_page(rows, requested_limit=1, default_limit=50, resource="documents") == [
        "newest"
    ]


def test_explicit_limit_equal_to_row_count_is_not_an_overflow() -> None:
    rows = ["b", "a"]
    assert newest_page(rows, requested_limit=2, default_limit=50, resource="runs") == rows
