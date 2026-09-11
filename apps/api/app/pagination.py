"""ADR-0021 untrusted, scope-bound keyset continuations; never authorization."""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from app.errors import api_error

Order = Literal["asc", "desc"]
Key = list[Any]
LEGACY_LIMIT = 50
MAX_LIMIT = 200


def _invalid() -> Any:
    return api_error(422, "INVALID_CURSOR", "Invalid continuation for this request.")


def _timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC).isoformat()


def scope(
    endpoint: str,
    org_id: uuid.UUID | str,
    resource_id: uuid.UUID | str | None = None,
    as_of: datetime | None = None,
    corpus_version_id: uuid.UUID | None = None,
    target_version_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "endpoint": endpoint,
        "org_id": str(org_id),
        "resource_id": str(resource_id) if resource_id else None,
        "as_of": as_of.astimezone(UTC).isoformat() if as_of else None,
        "corpus_version_id": str(corpus_version_id) if corpus_version_id else None,
    }
    if endpoint == "siblings":
        result["target_version_id"] = str(target_version_id) if target_version_id else None
    return result


def _scope(value: Any) -> dict[str, Any]:
    fields = {"endpoint", "org_id", "resource_id", "as_of", "corpus_version_id"}
    if not isinstance(value, dict):
        raise ValueError("scope")
    endpoint = value.get("endpoint")
    if endpoint not in {"documents", "workspaces", "runs", "siblings", "events"}:
        raise ValueError("endpoint")
    if endpoint == "siblings":
        fields.add("target_version_id")
    if value.keys() != fields:
        raise ValueError("scope fields")
    result = dict(value)
    for field in fields - {"endpoint", "as_of"}:
        item = value[field]
        if item is not None:
            if not isinstance(item, str):
                raise ValueError("uuid")
            result[field] = str(uuid.UUID(item))
    if result["org_id"] is None or (endpoint != "workspaces" and result["resource_id"] is None):
        raise ValueError("required scope id")
    if endpoint == "siblings" and (result["target_version_id"] is None or value["as_of"] is None):
        raise ValueError("reader scope")
    if value["as_of"] is not None:
        result["as_of"] = _timestamp(value["as_of"])
    return result


def _key(value: Any, endpoint: str) -> Key:
    if not isinstance(value, list):
        raise ValueError("key")
    if endpoint == "events":
        if len(value) != 1 or type(value[0]) is not int or not 0 <= value[0] <= 2**63 - 1:
            raise ValueError("sequence")
        return value
    count = 3 if endpoint in {"documents", "siblings"} else 2
    if len(value) != count or any(not isinstance(v, str) for v in value):
        raise ValueError("key fields")
    result = list(value)
    result[0] = _timestamp(value[0])
    result[-1] = str(uuid.UUID(value[-1]))
    if count == 3 and (not value[1] or len(value[1]) > 256 or "\x00" in value[1]):
        raise ValueError("accession")
    return result


@dataclass(frozen=True)
class Cursor:
    version: int
    scope: dict[str, Any]
    order: Order
    limit: int
    seek: Literal["after", "before"]
    high_water: Key
    anchor: Key


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def decode_cursor(token: str, expected_scope: dict[str, Any] | None = None) -> Cursor:
    try:
        if not 0 < len(token) <= 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("token")
        data = json.loads(
            base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True),
            object_pairs_hook=_pairs,
        )
        if not isinstance(data, dict) or data.keys() != {
            "version",
            "scope",
            "order",
            "limit",
            "seek",
            "high_water",
            "anchor",
        }:
            raise ValueError("fields")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("version")
        if type(data["limit"]) is not int or not 1 <= data["limit"] <= MAX_LIMIT:
            raise ValueError("limit")
        if data["order"] not in ("asc", "desc") or data["seek"] not in ("after", "before"):
            raise ValueError("direction")
        data["scope"] = _scope(data["scope"])
        if expected_scope is not None and data["scope"] != _scope(expected_scope):
            raise ValueError("scope mismatch")
        for field in ("high_water", "anchor"):
            data[field] = _key(data[field], data["scope"]["endpoint"])
        return Cursor(**data)
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        binascii.Error,
        RecursionError,
        OverflowError,
    ):
        raise _invalid() from None


def encode_cursor(cursor: Cursor) -> str:
    token = (
        base64.urlsafe_b64encode(
            json.dumps(
                asdict(cursor), sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    decode_cursor(token, cursor.scope)
    return token


def read_page(
    conn: Any,
    *,
    query: str,
    params: tuple[Any, ...],
    keys: tuple[str, ...],
    request_scope: dict[str, Any],
    limit: int | None = None,
    token: str | None = None,
    order: Order | None = None,
    default_limit: int = 50,
    max_limit: int = MAX_LIMIT,
    legacy_limit: int = LEGACY_LIMIT,
    force_page: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Bounded keyset reads. ``query``/``keys`` are trusted route SQL, never input.

    The route's base query must apply authorization and all evidence gates.
    SQL composition adds only parameterized high-water/seek keys and fixed order.
    """
    from psycopg import sql

    cursor = decode_cursor(token, request_scope) if token is not None else None
    if cursor and (
        (limit is not None and cursor.limit != limit)
        or (order is not None and cursor.order != order)
    ):
        raise _invalid()
    page_mode = force_page or limit is not None or cursor is not None
    size = cursor.limit if cursor else (limit or default_limit)
    if not 1 <= size <= max_limit:
        raise _invalid()
    presentation = cursor.order if cursor else (order or "asc")
    backwards = cursor is not None and cursor.seek == "before"
    sql_order = ("desc" if presentation == "asc" else "asc") if backwards else presentation
    columns: list[sql.Composable] = [sql.Identifier(k) for k in keys]
    if request_scope["endpoint"] in {"documents", "siblings"}:
        columns[1] = sql.SQL('{} COLLATE "C"').format(columns[1])
    key = sql.SQL("({})").format(sql.SQL(", ").join(columns))
    ordering = sql.SQL(", ").join(sql.SQL("{} {}").format(c, sql.SQL(sql_order)) for c in columns)
    base = sql.SQL("SELECT * FROM ({}) AS page_source").format(sql.SQL(query))

    def row_key(row: dict[str, Any]) -> Key:
        return [
            (
                value.isoformat()
                if isinstance(value, datetime)
                else value if type(value) is int else str(value)
            )
            for value in (row[k] for k in keys)
        ]

    high_water = cursor.high_water if cursor else None
    if page_mode and high_water is None:
        maximum = conn.execute(
            base
            + sql.SQL(" ORDER BY ")
            + sql.SQL(", ").join(sql.SQL("{} DESC").format(c) for c in columns)
            + sql.SQL(" LIMIT 1"),
            params,
        ).fetchone()
        if maximum is not None:
            high_water = row_key(maximum)
    conditions = []
    bound_params: list[Any] = []
    placeholders = sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() for _ in keys))
    if high_water is not None:
        conditions.append(sql.SQL("{} <= {}").format(key, placeholders))
        bound_params.extend(high_water)
    if cursor:
        op = ">" if (presentation == "asc") != backwards else "<"
        conditions.append(sql.SQL("{} {} {}").format(key, sql.SQL(op), placeholders))
        bound_params.extend(cursor.anchor)
    statement = base
    if conditions:
        statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
    statement += sql.SQL(" ORDER BY ") + ordering + sql.SQL(" LIMIT %s")
    take = size if page_mode else legacy_limit
    rows = conn.execute(statement, (*params, *bound_params, take + 1)).fetchall()
    overflow = len(rows) > take
    if not page_mode:
        if overflow:
            raise api_error(
                409,
                "PAGINATION_REQUIRED",
                "Use explicit pagination for this history.",
                {"limit": default_limit, "order": presentation},
            )
        return rows, None
    rows = rows[:size]
    if backwards:
        rows.reverse()
    metadata: dict[str, Any] = {
        "limit": size,
        "returned": len(rows),
        "next_cursor": None,
        "previous_cursor": None,
        "complete": cursor is None and not overflow,
    }
    if rows and high_water is not None:
        for direction, available, anchor in [
            ("after", (cursor is not None if backwards else overflow), row_key(rows[-1])),
            ("before", (overflow if backwards else cursor is not None), row_key(rows[0])),
        ]:
            if available:
                field = "next_cursor" if direction == "after" else "previous_cursor"
                metadata[field] = encode_cursor(
                    Cursor(
                        1,
                        request_scope,
                        presentation,
                        size,
                        cast(Literal["after", "before"], direction),
                        high_water,
                        anchor,
                    )
                )
    return rows, metadata


def page_headers(response: Any, metadata: dict[str, Any] | None) -> None:
    if metadata is None:
        return
    response.headers["X-FEL-Page-Limit"] = str(metadata["limit"])
    for field, name in [("next_cursor", "Next"), ("previous_cursor", "Previous")]:
        if metadata[field] is not None:
            response.headers[f"X-FEL-{name}-Cursor"] = metadata[field]
