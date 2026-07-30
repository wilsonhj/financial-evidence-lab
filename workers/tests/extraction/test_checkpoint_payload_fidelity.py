"""PR #145 review blocker 7: the truncation exemption covered only `text`.

`events.py` exempted `lowered == "text"` from its 64-char truncation, so
`description` / `definition` prose — and every issuer-supplied `dimensions` /
`qualifiers` value — was still cut inside `stage_output`. A resumed run
rehydrated mangled prose and computed a different `definition_hash` /
`raw_payload_hash` (and a different stage `input_hash`) than the run that
produced it.
"""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.events import redact_payload
from fel_workers.extraction.hashing import hash_json, sha256_hex, stage_input_hash
from fel_workers.extraction.serialize import serialize_stage_output

from .conftest import FIXTURE_SPAN

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_PINNED_TEXT = "ARR was $100 million as of June 30, 2026."

# Real filing prose is long; a fixture under 256 chars is exactly what let the
# truncation defect survive review.
LONG_DESCRIPTION = "Pricing actions across the enterprise tier contributed. " * 8
LONG_DEFINITION = "Annual recurring revenue, measured as of the period end. " * 8


# ---------------------------------------------------------------------------
# Blocker 7 — checkpoint payloads must round-trip prose byte for byte.
# ---------------------------------------------------------------------------


def _step_completed_payload(stage_output: Any) -> dict[str, Any]:
    return {
        "step_name": "extract_revenue_driver",
        "input_hash": sha256_hex("input"),
        "output_hash": hash_json(stage_output),
        "stage_output": serialize_stage_output(stage_output),
    }


def test_long_prose_survives_the_checkpoint_event_verbatim() -> None:
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
    stage_output = {"proposals": [driver]}

    stored = redact_payload(_step_completed_payload(stage_output))
    restored = stored["stage_output"]["proposals"][0]

    for key, original in driver.items():
        assert restored[key] == original, f"{key} was mangled inside stage_output"
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


def test_long_span_text_still_survives_the_checkpoint_event() -> None:
    """The exemption that already worked must keep working."""
    long_text = _PINNED_TEXT * 10
    stored = redact_payload(
        _step_completed_payload(
            [
                {
                    "source_span_id": FIXTURE_SPAN,
                    "text": long_text,
                    "text_hash": sha256_hex(long_text),
                }
            ]
        )
    )
    block = stored["stage_output"][0]
    assert block["text"] == long_text
    assert sha256_hex(block["text"]) == block["text_hash"]


def test_secrets_are_still_stripped_inside_a_checkpoint_payload() -> None:
    """Exempting truncation must not exempt redaction."""
    stored = redact_payload(
        _step_completed_payload({"prompt": "system prompt", "api_key": "sk-live", "ok": True})
    )
    assert stored["stage_output"]["prompt"] == "[redacted]"
    assert stored["stage_output"]["api_key"] == "[redacted]"
    assert stored["stage_output"]["ok"] is True


def test_incidental_event_strings_outside_stage_output_are_still_truncated() -> None:
    """The redaction intent is kept for strings nothing restores or hashes."""
    stored = redact_payload({"rationale": "x" * 400, "step_name": "normalize"})
    assert stored["rationale"].endswith("…[truncated]")
    assert len(stored["rationale"]) < 100
    assert stored["step_name"] == "normalize"
