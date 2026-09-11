"""Untrusted cursor inputs cannot change route/filter scope or query bounds."""

import base64
import json

import pytest

from app import pagination
from tests.conftest import requires_db

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


@pytest.mark.parametrize("value", [5, True, [], {}])
def test_scope_timestamp_is_strictly_typed(value):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as err:
        pagination.decode_cursor(token(scope={**SCOPE, "as_of": value}), SCOPE)
    assert err.value.status_code == 422


def test_equivalent_scope_uuid_and_timestamp_normalize():
    expected = {**SCOPE, "as_of": "2026-09-10T00:00:00Z"}
    alternate = {
        **SCOPE,
        "as_of": "2026-09-09T17:00:00-07:00",
        "org_id": SCOPE["org_id"].replace("-", ""),
    }
    c = pagination.decode_cursor(token(scope=alternate), expected)
    assert c.scope["org_id"] == SCOPE["org_id"]
    assert c.scope["as_of"] == "2026-09-10T00:00:00+00:00"


@requires_db
def test_workspace_keyset_uses_bounded_index_plan(db_url, org_fixture):
    import uuid

    import psycopg

    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, "
            "fiscal_calendar, as_of) SELECT gen_random_uuid(), %s, 'index-test', %s, "
            "'USD', 'FY', now() FROM generate_series(1, 10000)",
            (org_fixture[0], uuid.uuid4()),
        )
        conn.execute("ANALYZE workspaces")
        plan = conn.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM workspaces WHERE "
            "org_id=%s ORDER BY created_at, id LIMIT 51",
            (org_fixture[0],),
        ).fetchone()[0][0]["Plan"]
        assert plan["Actual Rows"] == 51
        assert plan["Plans"][0]["Node Type"] == "Index Scan"
        assert plan["Plans"][0]["Index Name"] == "workspaces_org_created_id_page_idx"
        assert plan["Plans"][0]["Actual Rows"] == 51


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_cursor_rejects_timestamp_utc_overflow(timestamp):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as err:
        pagination.decode_cursor(token(anchor=[timestamp, *KEY[1:]]), SCOPE)
    assert err.value.status_code == 422


def test_event_cursor_rejects_sequence_outside_postgres_integer_range():
    from fastapi import HTTPException

    event_scope = {**SCOPE, "endpoint": "events"}
    with pytest.raises(HTTPException) as err:
        pagination.decode_cursor(
            token(scope=event_scope, anchor=[2**63], high_water=[2**63]), event_scope
        )
    assert err.value.status_code == 422
