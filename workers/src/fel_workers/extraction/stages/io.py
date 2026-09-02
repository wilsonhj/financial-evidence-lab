"""Stage input/output payload shaping for the extraction FSM.

Both halves of a stage's content address live here: ``stage_input_payload``
builds the value ``stage_input_hash`` digests into the checkpoint key
``(run_id, step_name, input_hash, workflow_version)``, and ``restore_output``
puts a checkpointed stage output back into ``WorkflowState`` on resume.

The payload shapes are frozen: changing what a stage contributes here moves
that stage's ``input_hash`` and orphans every checkpoint already written under
the old key. ``test_checkpoint_hash_golden.py`` pins them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fel_workers.extraction.errors import IntegrityError
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.types import MODE_STAGES, EvidenceBlock, WorkflowState
from fel_workers.extraction.validate import validate_proposals


def stage_input_payload(state: WorkflowState, step_name: str) -> Any:
    req = state.request
    if step_name == "validate_request":
        return {
            "run_id": req.run_id,
            "modes": list(req.modes),
            "input_hash": req.input_hash,
            "ontology_version": req.ontology_version,
        }
    if step_name == "assemble_evidence":
        return {"manifest": req.input_manifest, "corpus_version_id": req.corpus_version_id}
    if step_name == "classify":
        return {"evidence_hashes": [e.text_hash for e in state.evidence]}
    if step_name == "collect_candidates":
        return {"classification": state.classification}
    if step_name in MODE_STAGES.values():
        return {"candidates": state.candidates, "classification": state.classification}
    if step_name == "normalize":
        return {"raw_proposals": state.raw_proposals}
    if step_name == "validate":
        return {"normalized": state.normalized}
    if step_name == "verify_citations":
        return {"validated_count": len(state.validated)}
    if step_name == "detect_conflicts":
        return {"proposal_ids": [p.id for p in state.validated]}
    if step_name == "persist_proposals":
        return {
            "proposal_ids": [p.id for p in state.validated],
            "conflict_keys": [c.conflict_key for c in state.conflicts],
        }
    return {"step": step_name}


def restore_output(state: WorkflowState, step_name: str, output: Any) -> None:
    if output is None:
        return
    if step_name == "assemble_evidence" and isinstance(output, list):
        restored: list[EvidenceBlock] = []
        for block in output:
            if isinstance(block, EvidenceBlock):
                restored.append(block)
                continue
            if not isinstance(block, dict):
                continue
            published = block.get("published_at")
            published_at = None
            if isinstance(published, datetime):
                published_at = published
            elif isinstance(published, str) and published:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            text = str(block.get("text") or "")
            text_hash = str(block["text_hash"])
            if sha256_hex(text) != text_hash:
                # Fail closed: re-extracting from altered text under the original
                # hash would emit proposals whose citations do not describe them.
                raise IntegrityError(
                    f"restored evidence for span {block['source_span_id']} does not "
                    "match its checkpointed text_hash"
                )
            restored.append(
                EvidenceBlock(
                    source_span_id=str(block["source_span_id"]),
                    document_version_id=str(block["document_version_id"]),
                    text=text,
                    text_hash=text_hash,
                    published_at=published_at,
                )
            )
        state.evidence = restored
    elif step_name == "classify" and isinstance(output, dict):
        state.classification = output
    elif step_name == "collect_candidates" and isinstance(output, dict):
        state.candidates = list(output.get("candidates") or [])
    elif step_name in MODE_STAGES.values() and isinstance(output, dict):
        proposals = output.get("proposals") or []
        if isinstance(proposals, list):
            state.raw_proposals.extend(proposals)
    elif step_name == "normalize" and isinstance(output, dict):
        state.normalized = list(output.get("normalized") or [])
    elif step_name == "validate" and isinstance(output, dict):
        state.normalized = list(output.get("normalized") or state.normalized)
        # Rebuild drafts so resume after validate does not lose proposals.
        rebuilt = validate_proposals(
            run_id=state.request.run_id,
            payloads=state.normalized,
            evidence_by_span=dict(evidence_map(state.evidence)),
        )
        state.validated = rebuilt.proposals
        state.conflicts = rebuilt.conflicts
    elif step_name == "detect_conflicts" and isinstance(output, dict):
        if not state.validated and state.normalized:
            rebuilt = validate_proposals(
                run_id=state.request.run_id,
                payloads=state.normalized,
                evidence_by_span=dict(evidence_map(state.evidence)),
            )
            state.validated = rebuilt.proposals
            state.conflicts = rebuilt.conflicts


def evidence_map(blocks: list[EvidenceBlock]) -> Mapping[str, dict[str, Any]]:
    return {
        b.source_span_id: {
            "document_version_id": b.document_version_id,
            "text": b.text,
            "text_hash": b.text_hash,
        }
        for b in blocks
    }


__all__ = ["evidence_map", "restore_output", "stage_input_payload"]
