"""Checkpoint fidelity now that the stage output lives in a column (ADR-0011).

Two guarantees that used to be in tension and no longer are.

**Fidelity.** A resumed run rehydrates the stage output and recomputes hashes
from it — ``raw_payload_hash``, ``proposal_id_for``, ``definition_hash``, and the
stage ``input_hash`` — so every string in it must round-trip byte for byte.
Before migration 0006 the only durable carrier was the ``step_completed`` event
payload, which meant the redactor had to be given a positional exemption for the
``stage_output`` subtree. Two earlier attempts to scope that exemption by field
name both corrupted the checkpoint: first only ``text`` was exempt so
``description``/``definition`` prose was truncated (PR #145 review blocker 7),
then truncation was suppressed but *substitution* was not, so an issuer-supplied
``qualifiers``/``dimensions`` key that happened to be named ``token`` became
``"[redacted]"`` and broke ``raw_payload_hash`` (PR #145 review M4).

**Metadata-only events.** The output now goes to
``extraction_run_steps.output``, hashed by ``output_hash``, and never passes
through the redactor at all — so fidelity is exact by construction, and the
exemption is deleted rather than narrowed. These tests pin both halves: the
serialized form round-trips verbatim and re-hashes identically, and the event
sink has no carve-out left for anything.
"""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.events import redact_event_payload, redact_log_payload
from fel_workers.extraction.hashing import hash_json, sha256_hex, stage_input_hash
from fel_workers.extraction.serialize import serialize_stage_output

from .conftest import FIXTURE_SPAN

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_PINNED_TEXT = "ARR was $100 million as of June 30, 2026."

# Real filing prose is long; a fixture under 256 chars is exactly what let the
# truncation defect survive review.
LONG_DESCRIPTION = "Pricing actions across the enterprise tier contributed. " * 8
LONG_DEFINITION = "Annual recurring revenue, measured as of the period end. " * 8


def _stored_output(stage_output: Any) -> Any:
    """What ``extraction_run_steps.output`` receives for this stage result."""
    return serialize_stage_output(stage_output)


# ---------------------------------------------------------------------------
# Fidelity — the column stores the payload verbatim and its hash describes it.
# ---------------------------------------------------------------------------


def test_long_prose_survives_the_durable_column_verbatim() -> None:
    """`description` / `definition` are hashed and rehydrated, so never truncate them."""
    assert len(LONG_DESCRIPTION) > 256 and len(LONG_DEFINITION) > 256
    driver = {
        "kind": "revenue_driver",
        "description": LONG_DESCRIPTION,
        "definition": LONG_DEFINITION,
        "raw_value": "pricing contributed to growth " * 12,
        "issuer_label": "Example SaaS",
        "dimensions": {"segment": "enterprise commentary " * 15},
        "qualifiers": {"scope": "consolidated narrative " * 15},
    }

    restored = _stored_output({"proposals": [driver]})["proposals"][0]

    for key, original in driver.items():
        assert restored[key] == original, f"{key} was mangled on the way to the column"
    # The hashes a resumed run recomputes from the restored payload must match.
    assert hash_json(restored) == hash_json(driver)
    assert sha256_hex(str(restored["definition"])) == sha256_hex(str(LONG_DEFINITION))
    assert stage_input_hash(
        run_id=_RUN_ID,
        step_name="normalize",
        payload={"raw_proposals": [restored]},
        workflow_version="extraction-workflow/v1",
    ) == stage_input_hash(
        run_id=_RUN_ID,
        step_name="normalize",
        payload={"raw_proposals": [driver]},
        workflow_version="extraction-workflow/v1",
    )


def test_long_span_text_survives_the_durable_column() -> None:
    """Pinned span text is re-verified against `text_hash` on resume."""
    long_text = _PINNED_TEXT * 10
    block = _stored_output(
        [
            {
                "source_span_id": FIXTURE_SPAN,
                "text": long_text,
                "text_hash": sha256_hex(long_text),
            }
        ]
    )[0]
    assert block["text"] == long_text
    assert sha256_hex(block["text"]) == block["text_hash"]


def test_issuer_supplied_key_named_like_a_secret_survives_in_the_column() -> None:
    """PR #145 review M4, restated for the column.

    `dimensions` and `qualifiers` carry issuer-supplied keys with arbitrary
    names, so no key-based rule can ever be safe over this subtree — a cohort
    qualifier an issuer happened to call `token`, or a payload field named `raw`,
    is data, not a secret. The column settles it structurally: nothing redacts
    the stored output, because nothing needs to.
    """
    driver = {
        "kind": "kpi",
        "metric_id": "nrr",
        "value": "118",
        "scale": 0,
        "raw": "118% net revenue retention",
        "qualifiers": {"token": "annual-cohort", "basis": "dollar"},
        "dimensions": {"token": "FY25", "segment": "enterprise"},
    }

    restored = _stored_output({"proposals": [driver]})["proposals"][0]

    assert restored["qualifiers"]["token"] == "annual-cohort"
    assert restored["dimensions"]["token"] == "FY25"
    assert restored["raw"] == "118% net revenue retention"
    # The hash a resumed run recomputes must still describe the same payload.
    assert hash_json(restored) == hash_json(driver)


# ---------------------------------------------------------------------------
# Metadata-only — the event sink has no exemption left, for any event type.
# ---------------------------------------------------------------------------


def test_event_sink_has_no_exemption_for_any_event_type() -> None:
    """The carve-out is deleted, not narrowed (ADR-0011 item 5).

    A payload carrying a `stage_output` key is redacted like anything else now,
    on `step_completed` as on every other event type. `workflow._run_stage` no
    longer writes such a key at all; this pins that nothing could smuggle source
    text through if it did.
    """
    payload = {
        "step_name": "assemble_evidence",
        "input_hash": sha256_hex("input"),
        "stage_output": {"text": _PINNED_TEXT},
    }
    for event_type in ("step_completed", "step_failed", "run_succeeded", "heartbeat"):
        stored = redact_event_payload(payload, event_type=event_type)
        assert stored["stage_output"]["text"] == "[redacted]", event_type
        assert stored["step_name"] == "assemble_evidence"


def test_event_and_log_sinks_now_redact_identically() -> None:
    """The two sinks diverged only because of the exemption; it is gone."""
    payload = {"stage_output": {"text": _PINNED_TEXT}, "step_name": "classify"}

    as_event = redact_event_payload(payload, event_type="step_completed")
    as_log = redact_log_payload(payload)

    assert as_event == as_log
    assert as_event["stage_output"]["text"] == "[redacted]"


def test_sensitive_keys_are_redacted_at_every_depth() -> None:
    """Defense in depth: prompts, keys and per-attempt request metadata."""
    payload = {
        "step_name": "classify",
        "input_hash": sha256_hex("input"),
        "prompt": "system prompt",
        "api_key": "sk-live",
        "model_step": {"api_key": "sk-live", "attempts": 1},
    }

    stored = redact_event_payload(payload, event_type="step_completed")

    assert stored["prompt"] == "[redacted]"
    assert stored["api_key"] == "[redacted]"
    assert stored["model_step"]["api_key"] == "[redacted]"
    assert stored["model_step"]["attempts"] == 1


def test_incidental_event_strings_are_truncated() -> None:
    """Nothing is restored or hashed from an event any more, so truncation is safe."""
    stored = redact_event_payload(
        {"rationale": "x" * 400, "step_name": "normalize"}, event_type="step_completed"
    )
    assert stored["rationale"].endswith("…[truncated]")
    assert len(stored["rationale"]) < 100
    assert stored["step_name"] == "normalize"
