"""Dimension map normalization.

The single implementation, called from ``payload.py::normalize_payload``. It
previously sat here unimported next to a private near-duplicate in
``payload.py`` (issue #155) which coerced instead of flagging — see
``normalize_dimensions`` for what that cost.
"""

from __future__ import annotations

from typing import Any


def normalize_dimensions(dimensions: Any) -> tuple[dict[str, str], list[str]]:
    """Order dimension keys; flag non-string entries instead of coercing them.

    ``extraction-payload/v1`` types ``dimensions`` as ``{string: string}`` and
    ``validate/schema.py`` checks it ("dimensions values must be strings"). That
    check could never fire, because the implementation this replaced
    (``payload.py::_normalize_dimensions``) ran ``str()`` over every key and
    value first: a model emitting ``{"segment": 42}`` reached review as a
    schema-clean ``{"segment": "42"}``, and ``{"region": {"eu": 1}}`` as the
    repr of a dict. The offending entry is dropped and reported as
    ``dimensions_non_string`` instead — a reviewer sees the problem, and no
    invented string is persisted as though the issuer had written it.

    A non-mapping ``dimensions`` raises, exactly as ``qualifiers`` and
    ``period`` do: ``pipeline.normalize_payload`` turns the raise into a blocker
    and carries the payload forward unchanged, so the ``normalize`` stage still
    counts it in ``blocked_count``. Returning an empty map plus a blocker
    instead would have discarded the payload's own dimensions *and* dropped it
    out of that count.
    """
    if dimensions is None:
        return {}, []
    if not isinstance(dimensions, dict):
        raise ValueError("dimensions must be an object")
    out: dict[str, str] = {}
    blockers: list[str] = []
    for key, value in sorted(dimensions.items(), key=lambda kv: str(kv[0])):
        if not isinstance(key, str) or not isinstance(value, str):
            if "dimensions_non_string" not in blockers:
                blockers.append("dimensions_non_string")
            continue
        out[key] = value
    return out, blockers


__all__ = ["normalize_dimensions"]
