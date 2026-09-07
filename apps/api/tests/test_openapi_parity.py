"""#192: the frozen OpenAPI contract and the FastAPI route table must agree.

Drift here is silent and expensive: a path in the YAML that nothing serves
generates a client method that 404s, and a route the service exposes without a
contract entry is an undocumented public surface nobody reviewed.

The contract deliberately carries paths that are frozen ahead of their
implementation (ADR-0001 froze the whole v1 surface at M0). Those path items
are marked ``x-fel-status: planned``. This test asserts that the *unmarked*
paths are exactly the implemented routes, in both directions — so removing a
marker without shipping the route fails, and shipping a route without removing
the marker fails too.

No database is needed: both sides come from static declarations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPO_ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml"

# Path-item keys that are operations. Everything else at that level (parameters,
# summary, description, servers, and any x- extension) is not a route.
_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

# The two sides name path parameters differently on purpose: the contract uses
# camelCase ({workspaceId}) and Python uses snake_case ({workspace_id}). The
# *shape* of the path is what has to match, not the parameter spelling.
_PARAM = re.compile(r"\{[^}]*\}")


def _normalise(path: str) -> str:
    return _PARAM.sub("{}", path)


def _contract_operations() -> set[tuple[str, str]]:
    document: dict[str, Any] = yaml.safe_load(OPENAPI_PATH.read_text())
    operations: set[tuple[str, str]] = set()
    for path, item in document["paths"].items():
        if item.get("x-fel-status") == "planned":
            continue
        for key in item:
            if key.lower() in _HTTP_METHODS:
                operations.add((key.upper(), _normalise(path)))
    return operations


def _implemented_operations() -> set[tuple[str, str]]:
    """The routes FastAPI actually serves, via the schema it generates itself.

    Reading ``app.openapi()`` rather than walking ``app.routes`` is deliberate:
    routers are mounted lazily, so the route objects are not all materialised as
    plain routes, and the generated schema is the same source of truth the
    service publishes at /openapi.json.
    """
    from app.main import app

    schema: dict[str, Any] = app.openapi()
    return {
        (method.upper(), _normalise(path))
        for path, item in schema["paths"].items()
        for method in item
        if method.lower() in _HTTP_METHODS
    }


def _render(title: str, operations: set[tuple[str, str]]) -> str:
    if not operations:
        return ""
    listing = "\n".join(f"  {method} {path}" for method, path in sorted(operations))
    return f"\n{title}\n{listing}"


def test_openapi_paths_and_fastapi_routes_agree() -> None:
    contract = _contract_operations()
    implemented = _implemented_operations()

    missing_route = contract - implemented
    missing_contract = implemented - contract
    assert contract == implemented, (
        "OpenAPI and FastAPI disagree."
        + _render(
            "In the contract but not served (add the route, or mark the path"
            " item x-fel-status: planned):",
            missing_route,
        )
        + _render(
            "Served but not in the contract (add the path, or remove its"
            " x-fel-status: planned marker):",
            missing_contract,
        )
    )


def test_planned_paths_are_declared_and_not_served() -> None:
    """Every planned marker names a real, currently unserved path."""
    document: dict[str, Any] = yaml.safe_load(OPENAPI_PATH.read_text())
    planned = {
        _normalise(path)
        for path, item in document["paths"].items()
        if item.get("x-fel-status") == "planned"
    }
    # The marker exists to describe a real gap; an empty set would mean the
    # first test is trivially satisfied and this file is no longer guarding it.
    assert planned, "expected at least one planned contract path"
    served = {path for _, path in _implemented_operations()}
    assert not (planned & served), "a path marked planned is actually served"
