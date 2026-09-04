"""Newest-first bounded listings (#191).

List endpoints used to ``ORDER BY`` ascending and ``LIMIT`` the default, which
silently dropped the *newest* filings, workspaces, and reruns. The frozen
contract documents those lists as unbounded, so an omitted ``limit`` must not
truncate: if more rows exist than the default cap, the request fails closed
(413). An explicit ``limit`` is an opted-in page of the newest rows, which is
the only honest page until cursor pagination lands in a contract change.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


class ListTooLarge(Exception):
    """More rows exist than an omitted (default) list cap will return."""

    def __init__(self, resource: str, limit: int) -> None:
        super().__init__(resource)
        self.resource = resource
        self.limit = limit


def newest_page(
    rows: Sequence[T],
    *,
    requested_limit: int | None,
    default_limit: int,
    resource: str,
) -> list[T]:
    """Slice a newest-first fetch that included one extra row.

    Callers ``SELECT … ORDER BY … DESC LIMIT effective + 1``. When the extra
    row is present and the caller did not pass ``limit``, this raises rather
    than dropping it. An explicit ``limit`` returns the first ``limit`` rows.
    """
    effective = default_limit if requested_limit is None else requested_limit
    if len(rows) > effective:
        if requested_limit is None:
            raise ListTooLarge(resource, default_limit)
        return list(rows[:effective])
    return list(rows)
