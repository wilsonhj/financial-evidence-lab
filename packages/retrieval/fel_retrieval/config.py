"""Stable chunker identity inputs for later index-version pinning (M2-011)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

CHUNKER_VERSION = "fel-chunker/1.0.0"


def config_hash(config: dict[str, Any]) -> str:
    """Deterministic ``sha256:<hex>`` of a canonical JSON config object."""
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"sha256:{digest}"
