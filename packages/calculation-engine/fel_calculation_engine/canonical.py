"""Typed canonical JSON and content hashes (T0402 / T0403, issue #63 checklist).

Content addressing is only as strong as the encoding is injective. This encoder
is *typed*: a ``Decimal`` becomes ``{"$decimal": "1.5"}`` (representation
independent), a ``datetime`` becomes ``{"$datetime": "<UTC ISO>"}``, a
dataclass becomes ``{"$type": "<ClassName>", ...fields}``. Keys starting with
``$`` are reserved and rejected in user dictionaries, so no string or dict can
forge a typed value; ``None`` is JSON ``null`` and never a sentinel string.
Floats are rejected outright (Constitution II) rather than stringified — the
``default=str`` escape hatch that silently collapses distinct objects into one
string is exactly what this module exists to avoid.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fel_calculation_engine.errors import CanonicalizationError
from fel_calculation_engine.values import canonical_decimal

RESERVED_PREFIX = "$"


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str) and not isinstance(value, Enum):
        return value
    if isinstance(value, Enum):
        return _encode(value.value)
    if isinstance(value, float):
        raise CanonicalizationError("floats cannot be canonicalized; use Decimal")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError(f"non-finite Decimal {value} cannot be canonicalized")
        return {"$decimal": canonical_decimal(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise CanonicalizationError("naive datetimes cannot be canonicalized")
        return {"$datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        payload: dict[str, Any] = {"$type": type(value).__name__}
        for field in dataclasses.fields(value):
            payload[field.name] = _encode(getattr(value, field.name))
        return payload
    if isinstance(value, dict):
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"dict keys must be str, got {type(key).__name__}")
            if key.startswith(RESERVED_PREFIX):
                raise CanonicalizationError(
                    f"key {key!r} uses the reserved {RESERVED_PREFIX!r} prefix"
                )
            encoded[key] = _encode(item)
        return encoded
    if isinstance(value, list | tuple):
        return [_encode(item) for item in value]
    raise CanonicalizationError(f"cannot canonicalize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_encode(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(material: str | bytes) -> str:
    data = material if isinstance(material, bytes) else material.encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))


__all__ = ["RESERVED_PREFIX", "canonical_json", "content_hash", "sha256_hex"]
