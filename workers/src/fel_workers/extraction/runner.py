"""Bounded model-step runner: exactly one repair; REFUSE ≠ abstention."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fel_providers.interfaces import (
    StructuredGenerationRequest,
    StructuredLLMProvider,
    StructuredModelResult,
)
from fel_workers.extraction.budget import RunBudget
from fel_workers.extraction.errors import ProviderError, ProviderRefused, SchemaInvalid
from fel_workers.extraction.hashing import request_hash, step_key
from fel_workers.extraction.roles.base import MAX_ATTEMPTS, RoleSpec


@dataclass(frozen=True)
class Abstention:
    """Valid zero-proposal outcome (M3-WF-010). Not a refusal or failure."""

    reason: str


@dataclass(frozen=True)
class StepResult:
    step_key: str
    root_input_hash: str
    outcome: dict[str, object] | Abstention
    provider: str
    model: str
    response_ids: tuple[str, ...]
    attempt_request_hashes: tuple[str, ...]
    attempts: int
    instructions_hash: str


def _envelope_errors(parsed: dict[str, object], schema: dict[str, object]) -> list[str]:
    """Envelope-root required-key check (items validated separately for step-output)."""
    required = schema.get("required", [])
    if not isinstance(required, list):
        return []
    missing = [str(k) for k in required if k not in parsed]
    return [f"missing required keys: {missing}"] if missing else []


def _is_empty_proposals(parsed: dict[str, object]) -> bool:
    return "proposals" in parsed and parsed.get("proposals") == []


def run_model_step(
    *,
    provider: StructuredLLMProvider,
    spec: RoleSpec,
    evidence_blocks: list[dict[str, str]],
    budget: RunBudget,
    run_id: str,
    step_name: str,
    workflow_version: str,
    provider_ref: str,
    model_ref: str,
    max_output_tokens: int = 4096,
) -> StepResult:
    """One bounded model step: initial call, optional single schema-repair call."""
    messages = spec.build_messages(evidence_blocks)

    def request_for(msgs: list[dict[str, str]]) -> StructuredGenerationRequest:
        return StructuredGenerationRequest(
            schema_name=spec.schema_name,
            schema_version=spec.schema_version,
            json_schema=spec.json_schema,
            messages=msgs,
            max_output_tokens=max_output_tokens,
            temperature=0.0,
        )

    root_req = request_for(messages)
    root_input_hash = request_hash(
        provider_ref=provider_ref,
        model_ref=model_ref,
        schema_name=root_req.schema_name,
        schema_version=root_req.schema_version,
        json_schema=root_req.json_schema,
        messages=root_req.messages,
        max_output_tokens=root_req.max_output_tokens,
        temperature=root_req.temperature,
    )
    key = step_key(run_id, step_name, root_input_hash, workflow_version)

    response_ids: list[str] = []
    attempt_hashes: list[str] = []
    problems: list[str] = ["no attempt made"]
    prov = model = "unknown"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = request_for(messages)
        attempt_hashes.append(
            request_hash(
                provider_ref=provider_ref,
                model_ref=model_ref,
                schema_name=request.schema_name,
                schema_version=request.schema_version,
                json_schema=request.json_schema,
                messages=request.messages,
                max_output_tokens=request.max_output_tokens,
                temperature=request.temperature,
            )
        )
        budget.precheck(reserve_output_tokens=max_output_tokens)
        try:
            result: StructuredModelResult = provider.generate_structured(request)
        except Exception as exc:  # noqa: BLE001 — typed boundary
            raise ProviderError(f"provider raised on attempt {attempt}: {exc}") from exc

        prov, model = result.provider, result.model
        response_ids.append(result.response_id)
        budget.record(result)

        if result.provider != provider_ref or result.model != model_ref:
            raise ProviderError(
                f"response {result.provider!r}/{result.model!r} violates run pin "
                f"{provider_ref!r}/{model_ref!r}"
            )
        if result.refused:
            raise ProviderRefused(result.refusal or "provider refusal")
        if result.parsed is None:
            problems = ["output was not parseable JSON"]
        else:
            env_errors = _envelope_errors(result.parsed, spec.json_schema)
            if not env_errors:
                if _is_empty_proposals(result.parsed):
                    outcome: dict[str, object] | Abstention = Abstention(
                        "explicit zero-proposal envelope"
                    )
                else:
                    outcome = result.parsed
                return StepResult(
                    key,
                    root_input_hash,
                    outcome,
                    prov,
                    model,
                    tuple(response_ids),
                    tuple(attempt_hashes),
                    attempt,
                    spec.instructions_hash(),
                )
            problems = env_errors

        if attempt < MAX_ATTEMPTS:
            failed_output = (
                json.dumps(result.parsed, sort_keys=True)
                if result.parsed is not None
                else "(no parseable output)"
            )
            messages = messages + [
                {"role": "assistant", "content": failed_output},
                {
                    "role": "user",
                    "content": (
                        "Your previous output (above) failed schema validation: "
                        f"{problems[0]}. Return ONLY a JSON object conforming to "
                        "the schema."
                    ),
                },
            ]

    if problems == ["output was not parseable JSON"]:
        raise ProviderError(f"no parseable output after {MAX_ATTEMPTS} attempts")
    raise SchemaInvalid(f"schema validation failed after {MAX_ATTEMPTS} attempts: {problems[0]}")


__all__ = ["Abstention", "StepResult", "run_model_step"]
