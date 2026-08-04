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
from fel_workers.extraction.types import Role
from fel_workers.extraction.validate.schema import validate_payload_item

# Proposal-bearing roles and the single ``kind`` each one may emit. All three
# share ``role_envelope.v1.json`` (roles/base.py), so the schema alone cannot
# stop the KPI role from returning guidance items — and ``_stage_model`` appends
# every role's output to the shared ``state.raw_proposals``, so `modes=("kpi",)`
# would otherwise produce guidance proposals whose prompt never ran.
_ROLE_PROPOSAL_KIND: dict[Role, str] = {
    Role.KPI: "kpi",
    Role.GUIDANCE: "guidance",
    Role.DRIVER_MAPPER: "revenue_driver",
}


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


def _matches_type(value: object, expected: object) -> bool:
    types = expected if isinstance(expected, list) else [expected]
    for type_name in types:
        if type_name == "null" and value is None:
            return True
        if type_name == "object" and isinstance(value, dict):
            return True
        if type_name == "array" and isinstance(value, list):
            return True
        if type_name == "string" and isinstance(value, str):
            return True
        if type_name == "boolean" and isinstance(value, bool):
            return True
        if type_name == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if (
            type_name == "number"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return True
    return False


def _schema_errors(value: object, schema: dict[str, object], *, path: str = "$") -> list[str]:
    """Validate the closed subset of JSON Schema used by role envelopes.

    Provider SDK structured-output modes are not a trust boundary: mocks and
    future providers can still return extra fields. Validating only ``required``
    let those fields ride into the verbatim durable checkpoint. The committed
    role schemas use a small subset (type/required/properties/items/closure,
    enum, minLength and uniqueItems), implemented here without adding a runtime
    dependency.
    """
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(value, expected_type):
        return [f"{path}: expected {expected_type!r}"]

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: value is not in the allowed enum")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: string is shorter than {minimum}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [str(key) for key in required if key not in value]
            if missing:
                errors.append(f"{path}: missing required keys: {missing}")

        properties_raw = schema.get("properties", {})
        properties = properties_raw if isinstance(properties_raw, dict) else {}
        if schema.get("additionalProperties") is False:
            unknown = sorted(str(key) for key in value if key not in properties)
            if unknown:
                errors.append(f"{path}: unexpected keys: {unknown}")

        names_raw = schema.get("propertyNames")
        if isinstance(names_raw, dict):
            allowed_names = names_raw.get("enum")
            if isinstance(allowed_names, list):
                unknown = sorted(str(key) for key in value if key not in allowed_names)
                if unknown:
                    errors.append(f"{path}: unexpected keys: {unknown}")

        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                errors.extend(_schema_errors(child, child_schema, path=f"{path}.{key}"))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, path=f"{path}[{index}]"))
        if schema.get("uniqueItems") is True:
            markers = [json.dumps(item, sort_keys=True, default=str) for item in value]
            if len(markers) != len(set(markers)):
                errors.append(f"{path}: items must be unique")

    return errors


def _envelope_errors(parsed: dict[str, object], schema: dict[str, object]) -> list[str]:
    """Validate the complete closed role envelope before checkpointing it."""
    return _schema_errors(parsed, schema)


def _is_empty_proposals(parsed: dict[str, object]) -> bool:
    return "proposals" in parsed and parsed.get("proposals") == []


def _proposal_item_errors(parsed: dict[str, object], expected_kind: str) -> list[str] | None:
    """Return every per-item problem, or ``None`` when all items are clean.

    Every invalid item counts. Accepting the envelope as soon as one sibling
    validated admitted the rest verbatim *and* skipped the repair attempt, so a
    malformed payload reached normalize carrying no record of what was wrong
    with it. Rejecting the envelope instead spends the one repair the runner is
    allowed (``MAX_ATTEMPTS``) and fails typed if the model does not fix it —
    the fail-closed answer for rows a reviewer can never correct.

    Empty proposals are handled as Abstention before this runs.
    """
    if "proposals" not in parsed:
        return None
    proposals = parsed.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return None
    item_errors: list[str] = []
    for idx, item in enumerate(proposals):
        if not isinstance(item, dict):
            item_errors.append(f"proposals[{idx}] must be an object")
            continue
        kind = item.get("kind")
        if kind != expected_kind:
            item_errors.append(f"proposals[{idx}]: kind must be {expected_kind!r}, got {kind!r}")
        item_errors.extend(f"proposals[{idx}]: {e}" for e in validate_payload_item(item))
    return item_errors or None


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
                item_errors: list[str] | None = None
                expected_kind = _ROLE_PROPOSAL_KIND.get(spec.role)
                if expected_kind is not None:
                    item_errors = _proposal_item_errors(result.parsed, expected_kind)
                if item_errors is None:
                    return StepResult(
                        key,
                        root_input_hash,
                        result.parsed,
                        prov,
                        model,
                        tuple(response_ids),
                        tuple(attempt_hashes),
                        attempt,
                        spec.instructions_hash(),
                    )
                problems = item_errors
            else:
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
