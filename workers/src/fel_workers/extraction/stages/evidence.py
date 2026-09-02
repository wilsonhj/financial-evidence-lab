"""``assemble_evidence`` — pin the run's evidence blocks and prove their hashes."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.context import ExecCtx
from fel_workers.extraction.errors import CutoffViolation, IntegrityError
from fel_workers.extraction.hashing import sha256_hex


def stage_assemble_evidence(ctx: ExecCtx) -> list[dict[str, Any]]:
    state = ctx.state
    if ctx.deps.evidence_loader is not None:
        blocks = ctx.deps.evidence_loader(state.request)
    else:
        blocks = list(state.evidence)
    if not blocks:
        # Empty evidence is valid abstention path later — not an integrity error here.
        state.evidence = []
        return []
    for block in blocks:
        if not block.text_hash.startswith("sha256:"):
            raise IntegrityError(f"evidence text_hash missing for {block.source_span_id}")
        if sha256_hex(block.text) != block.text_hash:
            # Fail closed at ingest, not only on resume: the hash is the
            # citation's content address, so a digest that does not describe
            # the text makes every proposal cite evidence it cannot prove.
            raise IntegrityError(
                f"evidence text_hash does not describe its text for {block.source_span_id}"
            )
        if block.published_at is not None and block.published_at > state.request.as_of:
            raise CutoffViolation(f"span {block.source_span_id} published_at after as_of cutoff")
    state.evidence = blocks
    return [
        {
            "source_span_id": b.source_span_id,
            "document_version_id": b.document_version_id,
            "text": b.text,
            "text_hash": b.text_hash,
            "published_at": b.published_at.isoformat() if b.published_at else None,
        }
        for b in blocks
    ]


__all__ = ["stage_assemble_evidence"]
