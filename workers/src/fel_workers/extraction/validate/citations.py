"""Citation hash / span-pin verification."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.hashing import sha256_hex


def citation_errors(
    payload: dict[str, Any],
    *,
    evidence_by_span: dict[str, dict[str, Any]],
    expected_hashes: dict[str, str] | None = None,
) -> list[str]:
    """Verify a proposal is supported by at least one verified citation.

    The loop below only ever iterated spans the payload *cites*, so a proposal
    with an empty ``evidence`` list ran zero iterations and returned zero
    errors — an entirely uncited figure reached the review queue as
    ``ok: true, blockers: []``. The two checks that bracket the loop close that:

    * a proposal that cites nothing is blocked, because nothing supports it;
    * a proposal whose every citation is membership-only is blocked, because
      naming a pinned span asserts nothing about what the span says. This is the
      ``partial`` grade of ``pipeline.citation_status_for``, and that grade is
      the most a string-form citation (``"evidence": ["<span-id>"]``) can ever
      express — so without this, a model could clear the check by choosing a
      JSON shape. Only an asserted ``text_hash`` that matches the pinned span
      proves the role actually opened it through ``read_span``.
    """
    errors: list[str] = []
    evidence = payload.get("evidence") or payload.get("source_span_ids") or []
    span_ids: list[str] = []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, str):
                span_ids.append(item)
            elif isinstance(item, dict) and item.get("source_span_id"):
                span_ids.append(str(item["source_span_id"]))
    if not span_ids:
        return ["proposal cites no evidence"]
    verified = 0
    for span_id in span_ids:
        block = evidence_by_span.get(span_id)
        if block is None:
            errors.append(f"cited span not in pinned evidence: {span_id}")
            continue
        if expected_hashes and span_id in expected_hashes:
            actual = block.get("text_hash") or sha256_hex(block.get("text", ""))
            if actual != expected_hashes[span_id]:
                errors.append(f"span hash mismatch: {span_id}")
            else:
                verified += 1
    if not verified:
        errors.append("no verified citation: no cited span asserts a matching text_hash")
    return errors


# `verify_citations` used to live here: a second, richer-looking span-hash
# verifier that read as a fail-closed guarantee and had ZERO callers, so none of
# it ever ran. It is gone rather than left to imply a check that does not happen.
# The guarantees it appeared to make are enforced where they belong:
#
# * "pinned evidence text matches its content address" — `IntegrityError` in
#   `workflow._stage_assemble_evidence`, on every run, and again in
#   `workflow._restore_output` when a checkpoint is rehydrated on resume.
# * "a cited span exists in the pinned evidence" — `citation_errors` above.
# * "a citation's asserted span hash matches the pinned span" — the
#   `expected_hashes` branch of `citation_errors` above, which
#   `validate/pipeline.py::_collect_blockers` now actually populates.
# * "a citation marked invalid is recorded as such" —
#   `workflow._stage_verify_citations`, which sets `citation_status`.

__all__ = ["citation_errors"]
