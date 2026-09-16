"""Fail-closed deployment proof before business authentication (ADR-0027)."""

from __future__ import annotations

import re
from pathlib import Path

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from app.config import Settings
from app.errors import api_error


def _marker(storage_dir: str | None, target: str, name: str) -> bool:
    if not storage_dir or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}", target) is None:
        return False
    with (Path(storage_dir) / name).open("rb") as stream:
        contents = stream.read(81)
    return contents == target.encode("ascii")


def _permitted(config: Settings) -> bool:
    if config.deployment_mode == "public":
        return config.auth_mode == "supabase"
    if config.auth_mode != "mock":
        return False
    if config.deployment_mode == "reader-smoke":
        return _marker(config.storage_dir, config.reader_smoke_target, ".reader-smoke-target")
    if config.deployment_mode == "synthetic-http":
        if (
            config.allow_mock_llm != "1"
            or not config.database_url
            or config.postgres_hostaddr is not None
            or config.postgres_service is not None
        ):
            return False
        connection = conninfo_to_dict(config.database_url)
        if (
            connection.get("host") not in {"localhost", "127.0.0.1", "::1"}
            or "hostaddr" in connection
            or "service" in connection
        ):
            return False
        return _marker(config.storage_dir, config.synthetic_http_target, ".synthetic-http-target")
    return False


def require_auth_deployment(config: Settings) -> None:
    """No startup side effects; never retain path/DSN errors as exception context."""
    try:
        permitted = _permitted(config)
    except (OSError, ValueError, TypeError, ProgrammingError):
        # Marker/connection-info diagnostics may contain sensitive configuration.
        permitted = False
    if not permitted:
        raise api_error(503, "AUTH_UNAVAILABLE", "Identity verification unavailable.")
