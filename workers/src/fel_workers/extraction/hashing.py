"""Content-addressed hashes for stages, payloads, and repair-stable identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_hex(material: str | bytes) -> str:
    data = material if isinstance(material, bytes) else material.encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_json(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def stage_input_hash(*, run_id: str, step_name: str, payload: Any, workflow_version: str) -> str:
    """Root logical identity for a stage (stable across repair attempts)."""
    return hash_json(
        {
            "run_id": run_id,
            "step_name": step_name,
            "payload": payload,
            "workflow_version": workflow_version,
        }
    )


def step_key(run_id: str, step_name: str, root_input_hash: str, workflow_version: str) -> str:
    return hash_json([run_id, step_name, root_input_hash, workflow_version])


def request_hash(
    *,
    provider_ref: str,
    model_ref: str,
    schema_name: str,
    schema_version: str,
    json_schema: dict[str, object],
    messages: list[dict[str, str]],
    max_output_tokens: int,
    temperature: float,
) -> str:
    """Per-attempt request identity (repair mutates messages → different hash)."""
    return hash_json(
        [
            provider_ref,
            model_ref,
            schema_name,
            schema_version,
            json_schema,
            messages,
            max_output_tokens,
            temperature,
        ]
    )


def proposal_id_for(*, run_id: str, kind: str, metric_id: str, raw_payload_hash: str) -> str:
    """Deterministic UUIDv5-style hex id for idempotent proposal inserts."""
    digest = hashlib.sha256(f"{run_id}|{kind}|{metric_id}|{raw_payload_hash}".encode()).hexdigest()
    # Format as UUID string from digest bytes.
    return f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-" f"a{digest[17:20]}-{digest[20:32]}"


__all__ = [
    "canonical_json",
    "hash_json",
    "proposal_id_for",
    "request_hash",
    "sha256_hex",
    "stage_input_hash",
    "step_key",
]
