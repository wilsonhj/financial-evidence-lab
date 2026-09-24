"""Explicit local-only target setup for synthetic HTTP acceptance harnesses."""

from __future__ import annotations

import os
import re
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict


def prepare_synthetic_target(
    database_url: str, storage: Path, target: str, database_prefix: str
) -> None:
    """Never claim an existing foreign/unmarked store or a remote database."""
    try:
        connection = conninfo_to_dict(database_url)
        database = connection.get("dbname")
        if (
            os.environ.get("FEL_DEPLOYMENT_MODE") != "synthetic-http"
            or os.environ.get("FEL_AUTH_MODE") != "mock"
            or os.environ.get("FEL_ALLOW_MOCK_LLM") != "1"
            or os.environ.get("PGHOSTADDR") is not None
            or os.environ.get("PGSERVICE") is not None
            or "hostaddr" in connection
            or "service" in connection
            or connection.get("host") not in {"localhost", "127.0.0.1", "::1"}
            or not isinstance(database, str)
            or not database.startswith(database_prefix)
            or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}", target) is None
        ):
            raise ValueError("invalid")
        storage.mkdir(parents=True, exist_ok=True)
        marker = storage / ".synthetic-http-target"
        if marker.exists():
            with marker.open("rb") as stream:
                if stream.read(81) != target.encode("ascii"):
                    raise ValueError("marker")
        else:
            if any(storage.iterdir()):
                raise ValueError("unmarked storage")
            with marker.open("xb") as stream:
                stream.write(target.encode("ascii"))
        return
    except Exception:
        failure = ValueError("Synthetic target configuration unavailable")
    raise failure
