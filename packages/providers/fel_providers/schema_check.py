"""A small strict JSON-Schema checker for provider output (ADR-0012).

``jsonschema`` is not a dependency of this repository, and the schemas handed to
a structured-output provider are deliberately a narrow subset: object/array/
string/number/integer/boolean/null types, ``required``, ``properties``,
``additionalProperties: false``, ``items``, ``enum``, ``minItems``, ``maxItems``
and ``minLength``. This mirrors the hand-rolled checker the extraction worker
already applies to role envelopes; it is duplicated rather than imported so a
provider package never depends on a worker package.

The checker is *strict* in the direction that matters: an unknown keyword is
ignored (it cannot make invalid output look valid), while every keyword listed
above is enforced. Error strings name schema locations and JSON types only —
never values — because provider output is model text and must not reach a log or
an exception message.
"""

from __future__ import annotations

from typing import Any

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _matches_type(value: object, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    checker = _TYPE_CHECKS.get(expected)
    if checker is None:
        # Unknown type keyword: cannot judge, do not fabricate a pass/fail.
        return True
    if isinstance(value, bool) and checker is not bool:
        return False
    return isinstance(value, checker)


def schema_errors(value: object, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Return every violation of ``schema`` by ``value`` (empty list = valid)."""
    errors: list[str] = []

    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        if not _matches_type(value, expected_type):
            errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
            return errors
    elif isinstance(expected_type, list):
        if not any(isinstance(t, str) and _matches_type(value, t) for t in expected_type):
            errors.append(f"{path}: expected one of {expected_type}, got {type(value).__name__}")
            return errors

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        # Report the position, not the offending value.
        errors.append(f"{path}: value is not one of the {len(enum)} permitted enum members")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path}: string shorter than minLength {min_length}")

    if isinstance(value, dict):
        errors.extend(_object_errors(value, schema, path=path))

    if isinstance(value, list):
        errors.extend(_array_errors(value, schema, path=path))

    return errors


def _object_errors(value: dict[str, Any], schema: dict[str, Any], *, path: str) -> list[str]:
    errors: list[str] = []
    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if isinstance(key, str) and key not in value:
                errors.append(f"{path}: missing required property {key!r}")
    properties_raw = schema.get("properties")
    properties = properties_raw if isinstance(properties_raw, dict) else {}
    if schema.get("additionalProperties") is False:
        for key in value:
            if key not in properties:
                errors.append(f"{path}: unexpected property {key!r}")
    for key, child in value.items():
        child_schema = properties.get(key)
        if isinstance(child_schema, dict):
            errors.extend(schema_errors(child, child_schema, path=f"{path}.{key}"))
    return errors


def _array_errors(value: list[Any], schema: dict[str, Any], *, path: str) -> list[str]:
    errors: list[str] = []
    min_items = schema.get("minItems")
    if isinstance(min_items, int) and len(value) < min_items:
        errors.append(f"{path}: array shorter than minItems {min_items}")
    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and len(value) > max_items:
        errors.append(f"{path}: array longer than maxItems {max_items}")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            errors.extend(schema_errors(item, item_schema, path=f"{path}[{index}]"))
    return errors


__all__ = ["schema_errors"]
