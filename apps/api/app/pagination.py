"""ADR-0021 untrusted, scope-bound keyset continuations; never authorization."""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.errors import api_error

Order = Literal["asc", "desc"]
Key = list[str] | list[int]
LEGACY_LIMIT = 50
MAX_LIMIT = 200


def _invalid() -> Any:
    return api_error(422, "INVALID_CURSOR", "Invalid continuation for this request.")


def _timestamp(value: str) -> str:
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
    if value["as_of"] is not None:
        result["as_of"] = _timestamp(value["as_of"])
    return result


def _key(value: Any, endpoint: str) -> Key:
    if not isinstance(value, list):
        raise ValueError("key")
    if endpoint == "events":
        if len(value) != 1 or type(value[0]) is not int or value[0] < 0:
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


def decode_cursor(token: str, expected_scope: dict[str, Any]) -> Cursor:
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
        if data["scope"] != _scope(expected_scope):
            raise ValueError("scope mismatch")
        for field in ("high_water", "anchor"):
            data[field] = _key(data[field], data["scope"]["endpoint"])
        return Cursor(**data)
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, RecursionError):
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
