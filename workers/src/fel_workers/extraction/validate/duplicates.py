"""Duplicate detection via fingerprints and comparability keys."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fel_workers.extraction.hashing import canonical_json, hash_json


def _magnitude(payload: dict[str, Any], key: str) -> str | None:
    """The figure ``key`` states, as a canonical decimal at the payload's ``scale``.

    Normalization keeps the filing's own mantissa in ``value``/``low``/``high``
    and its declared exponent in ``scale`` rather than folding the two together,
    so neither half identifies a figure alone: ``"100"`` at scale 3 and ``"100"``
    at scale 6 are $100k and $100M. Identity is therefore keyed on the product,
    not on the literal pair — ``"100"`` at scale 6 and ``"100000000"`` at scale 0
    are one figure written two ways, and must fingerprint the same.

    A missing ``scale`` is read as 0 rather than skipped: the field is required
    on every numeric variant of the frozen contract, and reading it as "no
    exponent" keeps a malformed payload comparable to a well-formed one instead
    of quietly giving it a private bucket.
    """
    raw = payload.get(key)
    if raw is None:
        return None
    scale = payload.get("scale")
    exponent = scale if isinstance(scale, int) and not isinstance(scale, bool) else 0
    try:
        return str(Decimal(str(raw)).scaleb(exponent).normalize())
    except ArithmeticError:
        # Not a number. `validate_payload_item` and `range_errors` already block
        # it; keep the literal so two unparsable figures stay two figures.
        return f"unparsed:{raw!r}@{scale!r}"


def duplicate_groups(payloads: list[dict[str, Any]]) -> list[list[int]]:
    """Group indices that share kind+metric_id+period+unit+currency+magnitude.

    Unit and currency scope the fingerprint (as they do in
    ``comparability_key_for``): the same number reported in USD and in JPY is two
    figures, not one restated twice, and must not carry a ``duplicate_candidate``
    blocker. The numeric fields enter as ``_magnitude`` — mantissa times scale —
    so a figure and a figure 1000x larger can never fingerprint alike.
    """
    buckets: dict[str, list[int]] = {}
    for idx, payload in enumerate(payloads):
        key = hash_json(
            {
                "kind": payload.get("kind"),
                "metric_id": payload.get("metric_id"),
                "period": payload.get("period"),
                "unit": payload.get("unit"),
                "currency": payload.get("currency"),
                "value": _magnitude(payload, "value"),
                "low": _magnitude(payload, "low"),
                "high": _magnitude(payload, "high"),
                "category": payload.get("category"),
            }
        )
        buckets.setdefault(key, []).append(idx)
    return [members for members in buckets.values() if len(members) > 1]


def conflict_key_for(
    payload: dict[str, Any],
    *,
    ontology_comparability_key: str | None = None,
) -> str:
    """Deterministic conflict grouping key.

    Prefer the ontology comparability key (e.g. NRR ``base_quantity``) when
    present so non-comparable definitions never share a value_disagreement
    bucket. Fall back to payload shape including qualifiers.
    """
    if ontology_comparability_key:
        return hash_json(
            {
                "comparability": ontology_comparability_key,
                "kind": payload.get("kind"),
                "entity_id": payload.get("entity_id"),
                "period": payload.get("period"),
            }
        )
    # Careful fallback: the local comparability key, which includes qualifiers so
    # distinct NRR bases do not collide when ontology key construction failed
    # closed, plus unit/currency so a USD figure and a JPY one are never graded
    # as disagreeing about the same quantity.
    #
    # `scale` is deliberately absent from both branches. It carries magnitude,
    # and two figures that disagree about magnitude are exactly what a conflict
    # group exists to surface — keying on it would file them apart and hide the
    # disagreement. Magnitude belongs in `value_fingerprint`, not here.
    return hash_json({"kind": payload.get("kind"), **comparability_key_for(payload)})


def value_fingerprint(payload: dict[str, Any]) -> str:
    """Fingerprint of *what a payload claims*, for value_disagreement detection.

    Numeric fields enter as ``_magnitude`` so a scale disagreement is a value
    disagreement, and unit/currency are included so the same mantissa under a
    different unit of account never reads as agreement.
    """
    return hash_json(
        {
            "value": _magnitude(payload, "value"),
            "low": _magnitude(payload, "low"),
            "high": _magnitude(payload, "high"),
            "unit": payload.get("unit"),
            "currency": payload.get("currency"),
            "text": payload.get("text"),
            "category": payload.get("category"),
            "direction": payload.get("direction"),
            "raw_value": payload.get("raw_value"),
        }
    )


def comparability_key_for(payload: dict[str, Any]) -> dict[str, Any]:
    """Stable local comparability fingerprint: which figures may be compared.

    Full ontology-keyed strings are applied in ``validate.pipeline`` when
    building proposal drafts; this helper is the fallback ``conflict_key_for``
    uses when that construction failed closed, so the two notions of "the same
    quantity" have one definition rather than two that can drift.

    It carries no magnitude on purpose — comparability decides *whether* two
    figures may be compared, and figures at different scales must stay
    comparable so their disagreement is visible.
    """
    return {
        "metric_id": payload.get("metric_id"),
        "entity_id": payload.get("entity_id"),
        "period": payload.get("period"),
        "unit": payload.get("unit"),
        "currency": payload.get("currency"),
        "dimensions": payload.get("dimensions") or {},
        "qualifiers": payload.get("qualifiers") or {},
    }


# `find_duplicates` used to live here: a second duplicate detector keyed on the
# comparability dict alone, with ZERO callers anywhere including tests. It is
# gone rather than left as live ammunition — it read no value, no magnitude and
# no scale, so wiring it up would have declared two figures that merely describe
# the same quantity to be the same figure. `duplicate_groups` above is the one
# duplicate detector, and it fingerprints the magnitude.


def definition_hash_for(payload: dict[str, Any]) -> str:
    definition = payload.get("definition")
    return hash_json({"definition": definition, "metric_id": payload.get("metric_id")})


__all__ = [
    "canonical_json",
    "comparability_key_for",
    "conflict_key_for",
    "definition_hash_for",
    "duplicate_groups",
    "value_fingerprint",
]
