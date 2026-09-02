"""The model-backed stages: ``classify``, ``collect_candidates`` and the mode extractors.

One body serves all five roles — the role decides which slice of
``WorkflowState`` the outcome lands in — so the budget accounting, the
abstention handling and the audit hand-off are written once.
"""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.context import ExecCtx, ModelStepAudit, record_usage
from fel_workers.extraction.errors import ProviderRefused
from fel_workers.extraction.roles.base import ROLE_SPECS
from fel_workers.extraction.runner import Abstention, run_model_step
from fel_workers.extraction.types import Role, WorkflowState


def _evidence_dicts(state: WorkflowState) -> list[dict[str, str]]:
    return [{"source_span_id": e.source_span_id, "text": e.text} for e in state.evidence]


def stage_model(ctx: ExecCtx, role: Role, step_name: str) -> dict[str, Any]:
    spec = ROLE_SPECS[role]
    req = ctx.state.request
    # The budget is the only per-call usage ledger, so this step's share of it is
    # the delta across the call (repair attempt included).
    before_input = ctx.budget.input_tokens_used
    before_output = ctx.budget.output_tokens_used
    before_cost = ctx.budget.cost_usd
    try:
        result = run_model_step(
            provider=ctx.deps.structured_llm,
            spec=spec,
            evidence_blocks=_evidence_dicts(ctx.state),
            budget=ctx.budget,
            run_id=req.run_id,
            step_name=step_name,
            workflow_version=req.workflow_version,
            provider_ref=req.provider,
            model_ref=req.model,
            max_output_tokens=min(4096, req.max_output_tokens),
        )
    except ProviderRefused:
        # Refusal is a typed failure for the run (never abstention).
        raise
    ctx.model_calls += result.attempts
    ctx.model_audit = ModelStepAudit(
        # The accepted answer is the last attempt's, never the rejected one.
        provider_response_id=result.response_ids[-1] if result.response_ids else None,
        input_tokens=ctx.budget.input_tokens_used - before_input,
        output_tokens=ctx.budget.output_tokens_used - before_output,
        cost_usd=ctx.budget.cost_usd - before_cost,
        attempts=result.attempts,
        instructions_hash=result.instructions_hash,
        attempt_request_hashes=result.attempt_request_hashes,
        response_ids=result.response_ids,
    )
    record_usage(ctx)
    if isinstance(result.outcome, Abstention):
        ctx.state.abstained = True
        if role == Role.CLASSIFIER:
            ctx.state.classification = {
                "document_type": "unknown",
                "sections": [],
                "relevant_modes": list(req.modes),
                "abstained": True,
                "reason": result.outcome.reason,
            }
            return ctx.state.classification
        if role == Role.FACT_CANDIDATES:
            ctx.state.candidates = []
            return {"candidates": [], "abstained": True, "reason": result.outcome.reason}
        return {"proposals": [], "abstained": True, "reason": result.outcome.reason}

    outcome = result.outcome
    if not isinstance(outcome, dict):
        raise TypeError(f"role {role} returned non-object outcome")
    if role == Role.CLASSIFIER:
        ctx.state.classification = dict(outcome)
        return ctx.state.classification
    if role == Role.FACT_CANDIDATES:
        raw_candidates = outcome.get("candidates") or []
        candidates = list(raw_candidates) if isinstance(raw_candidates, list) else []
        ctx.state.candidates = [c for c in candidates if isinstance(c, dict)]
        return {"candidates": ctx.state.candidates}
    raw_proposals = outcome.get("proposals") or []
    proposals = list(raw_proposals) if isinstance(raw_proposals, list) else []
    # Stamp entity / issuer when mock omitted them.
    stamped: list[dict[str, Any]] = []
    for prop in proposals:
        if not isinstance(prop, dict):
            continue
        item = dict(prop)
        # Pin entity_id to the run request (overwrite model output).
        item["entity_id"] = req.entity_id
        item.setdefault("issuer_label", req.issuer_label)
        stamped.append(item)
    ctx.state.raw_proposals.extend(stamped)
    return {"proposals": stamped}


__all__ = ["stage_model"]
