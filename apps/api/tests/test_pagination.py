"""Untrusted cursor inputs cannot change route/filter scope or query bounds."""

import base64
import json

import pytest

from app import pagination

SCOPE = {
    "endpoint": "documents",
    "org_id": "00000000-0000-4000-8000-000000000001",
    "resource_id": "00000000-0000-4000-8000-000000000002",
    "as_of": None,
    "corpus_version_id": None,
}
KEY = ["2026-09-10T00:00:00+00:00", "accession", "00000000-0000-4000-8000-000000000003"]


def token(**changes):
    return (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "version": 1,
                    "scope": SCOPE,
                    "order": "asc",
                    "limit": 50,
                    "seek": "after",
                    "high_water": KEY,
                    "anchor": KEY,
                    **changes,
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
    )


def test_typed_cursor_round_trip_and_scope_binding():
    c = pagination.decode_cursor(token(), SCOPE)
    assert c.limit == 50
    assert pagination.decode_cursor(pagination.encode_cursor(c), SCOPE) == c
    for name, value in [
        ("endpoint", "workspaces"),
        ("org_id", SCOPE["resource_id"]),
        ("resource_id", SCOPE["org_id"]),
        ("as_of", "2026-01-01T00:00:00Z"),
    ]:
        with pytest.raises(Exception) as err:
            pagination.decode_cursor(token(), {**SCOPE, name: value})
        assert err.value.detail["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "changes",
    [{"limit": x} for x in [0, -1, 201, True, 1.5, "50"]]
    + [
        {"version": 2},
        {"extra": 1},
        {"seek": "around"},
        {"order": "up"},
        {"anchor": ["bad"]},
        {"anchor": ["2026-09-10", "a", KEY[2]]},
        {"anchor": [KEY[0], "a", "bad"]},
    ],
)
def test_invalid_typed_cursor_fields(changes):
    with pytest.raises(Exception) as err:
        pagination.decode_cursor(token(**changes), SCOPE)
    assert err.value.detail["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "raw", ["?", "x" * 2049, base64.urlsafe_b64encode(b'{"version":1,"version":1}').decode()]
)
def test_malformed_and_duplicate_fields(raw):
    with pytest.raises(Exception) as err:
        pagination.decode_cursor(raw, SCOPE)
    assert err.value.detail["code"] == "INVALID_CURSOR"
