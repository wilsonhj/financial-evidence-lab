"""Fact identity, value fingerprints, and duplicate grouping.

Two payloads describe the *same fact* only when everything that makes them
comparable agrees: kind, metric, entity, period, unit, currency, dimensions and
qualifiers. They are the same *reading* of that fact only when their economic
content agrees too. Those are the two questions this module answers, and it
answers each in exactly one place — ``comparability_key_for`` for identity and
``value_fingerprint`` for content — so duplicate grouping (``duplicate_groups``)
and conflict grouping (``conflict_key_for``) can never disagree about what makes
two figures the same.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fel_workers.extraction.hashing import canonical_json, hash_json

# Entries of the identity key that a metric's ontology comparability key already
# encodes: it names the metric and exactly the qualifiers that decide
# comparability for it (``fel_ontology.build_comparability_key``). Every other
# entry survives — the ontology key says nothing about dimensions, so an EMEA and
# an APAC figure share one and are still two facts.
_ONTOLOGY_SUPERSEDES = frozenset({"metric_id", "qualifiers"})


def comparability_key_for(payload: dict[str, Any]) -> dict[str, Any]:
    """Everything that must agree before two payloads describe the same fact.

    ``scale`` is deliberately absent: it is notation, not identity. The same
    figure written ``{"value": "1.2", "scale": 9}`` and ``{"value": "1200",
    "scale": 6}`` is one fact reported twice, and ``value_fingerprint`` is what
    decides whether the two readings agree.

    ``entity_id`` and ``qualifiers`` are included for the same reason
    ``dimensions`` and ``currency`` are: each one alone is enough to make two
    otherwise identical rows different facts. Two issuers reporting ARR of 100
    are not one figure restated (``entity_id``), and neither are consolidated ARR
    and constant-currency ARR (``qualifiers`` — the ontology treats those as
    non-comparable constructions, so collapsing them here would hand a reviewer a
    ``duplicate_candidate`` on two figures the ontology says cannot be compared).
    """
    return {
        "kind": payload.get("kind"),
        "metric_id": payload.get("metric_id"),
        "entity_id": payload.get("entity_id"),
        "period": payload.get("period"),
        "unit": payload.get("unit"),
        "currency": payload.get("currency"),
        "dimensions": payload.get("dimensions") or {},
        "qualifiers": payload.get("qualifiers") or {},
    }


def conflict_key_for(
    payload: dict[str, Any],
    *,
    ontology_comparability_key: str | None = None,
) -> str:
    """Deterministic conflict grouping key.

    Prefer the ontology comparability key (e.g. NRR ``base_quantity``) when
    present so non-comparable definitions never share a value_disagreement
    bucket. It replaces the metric and qualifier entries of the fact identity and
    nothing else; the remaining axes still have to agree. When key construction
    failed closed, the full fact identity is the fallback.
    """
    identity = comparability_key_for(payload)
    if ontology_comparability_key:
        identity = {k: v for k, v in identity.items() if k not in _ONTOLOGY_SUPERSEDES}
        identity["comparability"] = ontology_comparability_key
    return hash_json(identity)


def canonical_magnitude(value: Any, scale: Any) -> Any:
    """Scale-independent identity of one mantissa + exponent number.

    This contract stores numerics as a mantissa plus a decimal scale exponent
    (``normalize/numeric.py``), so ``("1.2", 9)`` and ``("1200", 6)`` are both
    $1.2bn and must reduce to the same token. The magnitude is
    ``mantissa * 10**scale``, computed by shifting the ``Decimal``'s own
    exponent: exact, free of context precision and rounding, and with no float
    anywhere near a reported figure.

    A missing or non-integer ``scale`` shifts nothing rather than guessing at a
    magnitude (a malformed one is already a blocker — ``range.scale_blockers``).
    A value that is not a finite number is returned untouched, so two different
    unparseable values stay two different values instead of collapsing onto a
    shared placeholder.
    """
    if value is None:
        return None
    try:
        mantissa = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return value
    if not mantissa.is_finite():
        return value
    sign, digits, exponent = mantissa.as_tuple()
    shift = scale if isinstance(scale, int) and not isinstance(scale, bool) else 0
    exponent = int(exponent) + shift
    trimmed = list(digits)
    while len(trimmed) > 1 and trimmed[-1] == 0:
        trimmed.pop()
        exponent += 1
    if trimmed == [0]:
        # Zero is one amount at every scale and carries no sign.
        return "0e0"
    return f"{'-' if sign else ''}{''.join(str(d) for d in trimmed)}e{exponent}"


def value_fingerprint(payload: dict[str, Any]) -> str:
    """Economic content of a payload, independent of how it was written.

    Every numeric field is reduced through ``canonical_magnitude`` against the
    payload's single declared ``scale`` (the normalizer reconciles a range's
    bounds onto one exponent — ``normalize/payload.py::_reconcile_scale``), so a
    figure restated in different magnitude words is not a ``value_disagreement``.

    ``raw_value`` is deliberately absent. It is issuer wording preserved verbatim
    by the normalizer, so hashing it would put "$1.2 billion" and "$1,200
    million" in disagreement on the strength of their punctuation — the very
    false positive normalizing the scale exists to remove.
    """
    scale = payload.get("scale")
    return hash_json(
        {
            "value": canonical_magnitude(payload.get("value"), scale),
            "low": canonical_magnitude(payload.get("low"), scale),
            "high": canonical_magnitude(payload.get("high"), scale),
            "text": payload.get("text"),
            "category": payload.get("category"),
            "direction": payload.get("direction"),
        }
    )


def duplicate_groups(payloads: list[dict[str, Any]]) -> list[list[int]]:
    """Group indices that are the same fact reported with the same value.

    A duplicate is one figure stated twice, so both halves have to match: the
    fact identity (``comparability_key_for``) *and* the economic content
    (``value_fingerprint``). The same fact with disagreeing values is a conflict
    for ``conflicts.detect_conflicts`` to raise, not a ``duplicate_candidate``.
    """
    buckets: dict[str, list[int]] = {}
    for idx, payload in enumerate(payloads):
        key = hash_json(
            {
                "identity": comparability_key_for(payload),
                "value": value_fingerprint(payload),
            }
        )
        buckets.setdefault(key, []).append(idx)
    return [members for members in buckets.values() if len(members) > 1]


def definition_hash_for(payload: dict[str, Any]) -> str:
    definition = payload.get("definition")
    return hash_json({"definition": definition, "metric_id": payload.get("metric_id")})


__all__ = [
    "canonical_json",
    "canonical_magnitude",
    "comparability_key_for",
    "conflict_key_for",
    "definition_hash_for",
    "duplicate_groups",
    "value_fingerprint",
]
