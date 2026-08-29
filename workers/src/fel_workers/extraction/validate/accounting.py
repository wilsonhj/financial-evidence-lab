"""Accounting checks: per-payload rules and cross-payload arithmetic identities.

Two layers, both reached from ``validate.pipeline.validate_proposals``:

* :func:`accounting_errors` — one payload at a time: the ``svc_gm``
  blended-margin prohibition, percent plausibility, the ``billings`` derivation
  lineage gate, ``crpo`` timing verification, guidance range ordering, and the
  ontology's required qualifiers.
* :func:`identity_errors` — arithmetic identities across payloads, required by
  spec M3-VAL-001: cRPO never exceeds RPO, single-dimension segments sum to
  their reported total, and gross profit equals revenue minus COGS.

The numeric contract (``extraction-payload/v1``) stores a **mantissa plus a
decimal scale exponent**: ``{"value": "1.2", "scale": 9}`` is $1.2bn, and
``normalize/numeric.py`` deliberately never collapses the pair. Every
comparison here therefore reconstructs the magnitude with
:func:`_magnitude` before comparing — two payloads for the same figure may
legitimately carry different scales (``"1200"``/6 and ``"1.2"``/9), and
comparing the mantissas alone would report a break that does not exist.
:func:`_magnitude` shifts the ``Decimal`` exponent directly rather than
multiplying by ``10 ** scale``, so it is exact and independent of the
ambient decimal context precision.

Identity comparisons use a **relative** tolerance
(:data:`IDENTITY_RELATIVE_TOLERANCE`), never a fixed epsilon: the same absolute
gap that is a real break between two $5m figures is rounding noise between two
$50bn figures, so an absolute epsilon is either deafening at the top of the
range or deaf at the bottom.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fel_ontology.models import MetricDef, OntologyDocument
from fel_workers.extraction.hashing import canonical_json
from fel_workers.extraction.validate.range import check_range

# 0.5% of the larger side. Issuers routinely report segments to three
# significant figures against a total reported to four, which lands a few tenths
# of a percent apart; a genuine identity break is orders of magnitude larger.
IDENTITY_RELATIVE_TOLERANCE = Decimal("0.005")

IDENTITY_PREFIX = "accounting_identity_violation:"

# svc_gm must never be treated as blended company gross margin.
_BLENDED_MARGIN_MARKERS = frozenset(
    {
        "blended",
        "company",
        "consolidated",
        "total_gm",
        "total_gross_margin",
        "blended_margin",
    }
)

# The unit is issuer-facing text, not a closed enum, so an exact ``== "percent"``
# match silently skipped every payload that spelled it "%" or "pct" — precisely
# the payloads a percent bound exists to catch.
_PERCENT_UNITS = frozenset({"percent", "percentage", "percentage_points", "%", "pct", "pp"})

# Kinds that carry a numeric magnitude worth checking (revenue_driver does not).
_NUMERIC_KINDS = frozenset({"kpi", "guidance"})

# Free-text metric ids the gross-profit identity recognises. They are not
# ontology metrics (the saas-metrics ontology covers SaaS KPIs, not the income
# statement), so they arrive as issuer-labelled guidance/KPI ids.
_REVENUE_ID = "revenue"
_COGS_ID = "cogs"
_GROSS_PROFIT_ID = "gross_profit"


def _is_percent_unit(unit: Any) -> bool:
    return isinstance(unit, str) and unit.strip().lower() in _PERCENT_UNITS


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _magnitude(value: Decimal, scale: Any) -> Decimal:
    """Reconstruct mantissa + scale exponent into a single comparable Decimal.

    ``{"value": "1.2", "scale": 9}`` becomes ``Decimal("1.2E+9")``. Implemented
    by shifting the Decimal's own exponent so the result is exact regardless of
    the ambient context precision (``value * 10 ** scale`` rounds at 28
    significant digits, and ``Decimal.scaleb`` is context-sensitive too).
    """
    exponent = _int_or_none(scale)
    if not exponent:
        return value
    sign, digits, current = value.as_tuple()
    if not isinstance(current, int):  # NaN / Infinity carry a string exponent.
        return value
    return Decimal((sign, digits, current + exponent))


def accounting_errors(payload: dict[str, Any], ontology: OntologyDocument) -> list[str]:
    """Per-payload accounting blockers used by ``validate_proposals``."""
    metric_id = payload.get("metric_id")
    if not isinstance(metric_id, str):
        return ["metric_id missing"]
    try:
        metric = ontology.metric(metric_id)
    except KeyError:
        # Unknown metrics are allowed for guidance/driver free-text IDs but flagged.
        return [f"unknown ontology metric_id: {metric_id}"] if payload.get("kind") == "kpi" else []

    errors: list[str] = []
    errors.extend(_svc_gm_errors(metric_id, payload))
    errors.extend(_percent_errors(metric, payload))
    errors.extend(_metric_rule_errors(metric_id, payload))

    # Share Decimal low/high ordering with check_range; keep live-path messages.
    for code in check_range(payload):
        if code == "range_low_gt_high":
            errors.append("guidance range low must be <= high")
        elif code == "range_bounds_not_decimal":
            errors.append("guidance range low/high not decimal")
        else:
            errors.append(code)

    quals = payload.get("qualifiers") or {}
    for field in metric.required_qualifiers:
        if field not in quals or not str(quals.get(field, "")).strip():
            errors.append(f"missing required qualifier: {field}")
    return errors


def _svc_gm_errors(metric_id: str, payload: dict[str, Any]) -> list[str]:
    """svc_gm must never be presented as blended company gross margin."""
    if metric_id != "svc_gm":
        return []
    errors: list[str] = []
    quals = payload.get("qualifiers") or {}
    scope = str(quals.get("margin_scope", "")).lower()
    if any(marker in scope for marker in _BLENDED_MARGIN_MARKERS):
        errors.append("svc_gm must never proxy blended company gross margin")
    if "blended" in str(payload.get("definition") or "").lower():
        errors.append("svc_gm definition must not claim blended margin")
    if quals.get("basis") == "blended":
        errors.append("svc_gm_blended_forbidden")
    return errors


def _percent_errors(metric: MetricDef, payload: dict[str, Any]) -> list[str]:
    """Percent plausibility on the *scaled* magnitude, for any spelling of the unit.

    Two defects fixed here. The bound used to read ``value`` and ignore
    ``scale``, so ``{"value": "1.5", "scale": 3}`` — 1500% — read as 1.5 and
    passed; and the margin bound matched ``unit == "percent"`` exactly, so the
    same figure labelled "%" or "pct" skipped the check entirely. ``low`` and
    ``high`` are covered too: a percent guidance range never carried a bound.
    """
    if metric.value_type != "ratio_pct" or payload.get("kind") not in _NUMERIC_KINDS:
        return []
    errors: list[str] = []
    scale = payload.get("scale")
    if _int_or_none(scale) not in (None, 0):
        # A percentage is never written with a magnitude suffix, so a non-zero
        # exponent means the issuer text was misread before normalization.
        errors.append(f"percent value must use scale 0, got {scale}")
    is_margin = metric.id in {"sub_gm", "svc_gm"}
    percent_unit = _is_percent_unit(payload.get("unit"))
    for key in ("value", "low", "high"):
        if payload.get(key) is None:
            continue
        parsed = _decimal_or_none(payload[key])
        if parsed is None:
            # Worded exactly as range_errors words it, so pipeline._dedupe
            # collapses the overlap into one finding for the reviewer.
            errors.append(f"{key} is not a decimal string")
            continue
        magnitude = _magnitude(parsed, scale)
        # Ratios expressed as percent points commonly 0–200; soft range flag.
        if magnitude < Decimal("-100") or magnitude > Decimal("500"):
            errors.append(f"ratio percent out of plausible range: {magnitude}")
        if is_margin and percent_unit and magnitude > Decimal("100"):
            errors.append("margin_percent_out_of_range")
    return errors


def _metric_rule_errors(metric_id: str, payload: dict[str, Any]) -> list[str]:
    """Metric-specific derivation and verification gates."""
    blockers: list[str] = []
    quals = payload.get("qualifiers") or {}
    if metric_id == "billings" and payload.get("reported_or_derived") == "derived":
        # Billings may only be derived from cited revenue + Δ deferred revenue.
        lineage = quals.get("derivation_inputs")
        if not isinstance(lineage, list) or len(lineage) < 2:
            blockers.append("billings_derivation_inputs_missing")
    if metric_id == "crpo":
        # cRPO needs its timing dimension verified before it means anything.
        dims = payload.get("dimensions") or {}
        if "horizon" not in dims and "timing_verified" not in quals:
            blockers.append("crpo_timing_unverified")
    return blockers


@dataclass(frozen=True)
class _Fact:
    """One numeric payload reduced to what an identity needs to compare."""

    index: int
    metric_id: str
    entity_id: str
    period: str
    unit: str
    currency: str
    dimensions: tuple[tuple[str, str], ...]
    magnitude: Decimal


def _facts(payloads: list[dict[str, Any]]) -> list[_Fact]:
    facts: list[_Fact] = []
    for index, payload in enumerate(payloads):
        if payload.get("kind") != "kpi":
            continue
        metric_id = payload.get("metric_id")
        value = _decimal_or_none(payload.get("value"))
        if value is None or not isinstance(metric_id, str):
            continue
        dims = payload.get("dimensions") or {}
        if not isinstance(dims, dict):
            continue
        facts.append(
            _Fact(
                index=index,
                metric_id=metric_id,
                entity_id=str(payload.get("entity_id") or ""),
                period=canonical_json(payload.get("period")),
                # Whitespace-trimmed but deliberately NOT case-folded. Issue
                # #153 tracks the real defect: 'usd' and 'USD' key different
                # slices here, so an identity spanning both is skipped rather
                # than checked.
                #
                # Case-folding *only here* was tried and reverted, because it
                # makes things worse rather than better.
                # `duplicates.comparability_key_for` does not fold, so folding
                # this side alone breaks the contract `_sole` relies on: two
                # rows differing only in unit case merge into one slice, `_sole`
                # correctly backs off to `validate.conflicts` — and conflicts,
                # still keyed on the unfolded unit, never sees the pair. A real
                # identity break then vanishes with no blocker from any checker,
                # where before the fold it was caught. Both sides have to fold
                # together, and `comparability_key_for` feeds the conflict
                # identity, so that is a contract change with persisted-id
                # consequences — #153, not a one-line edit here.
                #
                # `.strip()` stays: whitespace carries no semantic distinction,
                # so trimming cannot over-merge, and it keeps direct
                # `identity_errors` callers (the test suite, anything bypassing
                # the normalizer) from silently dropping a ' USD' row out of
                # its slice.
                unit=str(payload.get("unit") or "").strip(),
                currency=str(payload.get("currency") or ""),
                dimensions=tuple(sorted((str(k), str(v)) for k, v in dims.items())),
                # Mantissa + exponent collapsed exactly once, here, so every
                # identity below compares like with like (see module docstring).
                magnitude=_magnitude(value, payload.get("scale")),
            )
        )
    return facts


def relatively_equal(
    actual: Decimal,
    expected: Decimal,
    *,
    tolerance: Decimal = IDENTITY_RELATIVE_TOLERANCE,
) -> bool:
    """Compare two magnitudes within a tolerance *proportional* to their size.

    Exposed so the tolerance can be exercised directly: the property that makes
    it correct is that the admissible absolute gap scales with the figures, not
    that any particular gap passes.
    """
    reference = max(abs(actual), abs(expected))
    if reference == 0:
        return actual == expected
    return abs(actual - expected) <= tolerance * reference


def _record(out: dict[int, list[str]], facts: Iterable[_Fact], code: str) -> None:
    for fact in facts:
        codes = out.setdefault(fact.index, [])
        if code not in codes:
            codes.append(code)


def identity_errors(
    payloads: list[dict[str, Any]],
    *,
    excluded_indices: frozenset[int] = frozenset(),
) -> dict[int, list[str]]:
    """Cross-payload arithmetic identities (M3-VAL-001), keyed by payload index.

    Every member of a broken identity is flagged, not just the outlier: nothing
    here can tell which figure is wrong, and guessing would send a reviewer to
    the wrong row.

    ``excluded_indices`` drops specific payloads from identity consideration
    entirely, before a single ``_Fact`` is built for them. ``validate.pipeline``
    passes the indices of rows the *normalizer* already rejected
    (``NORMALIZER_BLOCKERS_KEY``) here. Without this, such a row still produces
    a ``_Fact``, and a slice holding one clean fact plus one rejected one looks
    exactly like two genuinely competing facts to ``_sole`` — which correctly
    backs off an identity for *that* case, since two competing real facts are a
    value disagreement for ``validate.conflicts`` to own, not a broken
    identity. A normalizer-rejected row never earned that seat at the table:
    left in, it silently disables the identity for every clean sibling sharing
    its slice too (PR #145 review M1).
    """
    built = _facts(payloads)
    facts = [fact for fact in built if fact.index not in excluded_indices]
    # Withholding behaves differently for a SUM than for a COMPARISON, so only
    # `_check_segment_sums` is told about it.
    #
    # The relational identities (rpo/crpo, gross profit) compare named members
    # of a slice. Dropping a rejected row there is what restores a clean 1:1
    # match for `_sole`, and is exactly the fix PR #145 review M1 made: a
    # rejected sibling must not disable the identity for its clean rows.
    #
    # A segment sum is arithmetic over every member, so a dropped row is a
    # MISSING ADDEND, not an absent competitor. The remaining rows still
    # satisfy every precondition the check tests, so it evaluates a partial
    # breakdown and reports `segments_do_not_sum` for a shortfall that is
    # purely an artefact of the exclusion -- convicting the clean siblings
    # while the row that actually had the problem goes unflagged. That group
    # cannot be evaluated at all, so it is suppressed rather than guessed at.
    #
    # LIMIT OF THIS SUPPRESSION, so the next reader does not over-trust it:
    # `_check_segment_sums` matches a withheld addend -- a single-dimension
    # row, the only shape that can be one -- to its siblings by
    # `(metric_id, entity_id, period, unit, currency)`. That works only when
    # the fields forming the key SURVIVED normalization -- which is not
    # guaranteed for exactly the rows that get withheld. A segment whose
    # `currency` is absent keys on `""` and never matches its `USD` siblings;
    # one rejected outright yields no `_Fact` at all (`_facts` skips a payload
    # whose `dimensions` is not a mapping) and so never reaches `withheld`.
    # Both still convict the clean siblings. Neither is a regression -- `main`
    # behaves identically -- but neither is fixed here, and closing them means
    # keying the suppression on something the withheld row cannot corrupt,
    # which has to be weighed against silencing a real break in a genuinely
    # different currency slice (see
    # `test_suppressing_one_slice_does_not_silence_a_real_break_in_another`).
    withheld = [fact for fact in built if fact.index in excluded_indices]
    out: dict[int, list[str]] = {}
    _check_rpo_balance(facts, out)
    _check_segment_sums(facts, out, withheld)
    _check_gross_profit(facts, out)
    return out


def _context(fact: _Fact, *, ignore_dimensions: frozenset[str] = frozenset()) -> tuple[Any, ...]:
    """The slice two facts must share before an identity may relate them.

    Currency is part of it because conversion is out of scope: RPO in USD and
    cRPO in EUR are not two sides of one identity. ``ignore_dimensions`` drops
    dimension keys that mark *what a metric is* rather than which slice of it
    this row covers.
    """
    dimensions = tuple(
        (name, value) for name, value in fact.dimensions if name not in ignore_dimensions
    )
    return (fact.entity_id, fact.period, fact.unit, fact.currency, dimensions)


def _by_metric(group: list[_Fact]) -> dict[str, list[_Fact]]:
    indexed: dict[str, list[_Fact]] = {}
    for fact in group:
        indexed.setdefault(fact.metric_id, []).append(fact)
    return indexed


def _sole(indexed: dict[str, list[_Fact]], metric_id: str) -> _Fact | None:
    """The single fact for ``metric_id``, or None when absent or ambiguous.

    An identity over a slice that holds two competing RPO figures is not a
    broken identity, it is a value disagreement — ``validate.conflicts`` owns
    that, and flagging it here too would double-report one problem.
    """
    found = indexed.get(metric_id) or []
    return found[0] if len(found) == 1 else None


def _check_rpo_balance(facts: list[_Fact], out: dict[int, list[str]]) -> None:
    """cRPO is the portion of RPO due within the horizon, so it cannot exceed it.

    ``horizon`` is excluded from the slice: it is cRPO's own definitional timing
    marker (``_metric_rule_errors`` requires it), not a segment of the balance.
    Keeping it in the key would put every real cRPO row in a different group
    from the RPO it must not exceed, and the identity would never fire.

    Both sides are compared by magnitude, for the same reason
    ``_check_gross_profit`` discards COGS' polarity. RPO and cRPO are declared
    ``kind: balance`` in the ontology — a performance-obligation backlog, which
    is never truly a negative quantity — so a negative value arriving here is a
    parenthesized-presentation artifact of this PR's own
    ``normalize/numeric.py`` parens handling, not a claim the balance itself is
    negative. Left signed, the comparison inverts exactly as the gross-profit
    identity did before it was fixed, and in both directions:
    ``rpo=1000, crpo=-1500`` reads ``-1500 > 1000`` as false and certifies a
    real violation clean, while ``rpo=-1000, crpo=300`` reads ``300 > -1000`` as
    true and blocks an entirely valid pair. Comparing ``abs()`` restores the
    only question this identity is asking: is the near-term portion larger than
    the whole backlog it is a portion of.

    Note that ``_check_segment_sums`` must NOT be given this treatment. It is
    additive rather than subtractive, so signed magnitudes are already correct
    there: a contra segment (a returns or allowance line) is legitimately
    negative, and ``abs()``-ing the parts would make a correct breakdown stop
    summing to its total. There is deliberately no central polarity pass over
    ``_Fact`` — the three identities need three different sign conventions.
    """
    ignore = frozenset({"horizon"})
    groups: dict[tuple[Any, ...], list[_Fact]] = {}
    for fact in facts:
        if fact.metric_id in {"rpo", "crpo"}:
            groups.setdefault(_context(fact, ignore_dimensions=ignore), []).append(fact)
    for group in groups.values():
        indexed = _by_metric(group)
        rpo, crpo = _sole(indexed, "rpo"), _sole(indexed, "crpo")
        if rpo is None or crpo is None:
            continue
        rpo_size, crpo_size = abs(rpo.magnitude), abs(crpo.magnitude)
        if crpo_size > rpo_size and not relatively_equal(crpo_size, rpo_size):
            _record(out, (rpo, crpo), f"{IDENTITY_PREFIX}crpo_exceeds_rpo")


def _check_segment_sums(
    facts: list[_Fact], out: dict[int, list[str]], withheld: Iterable[_Fact]
) -> None:
    """A reported total must equal the sum of its single-dimension segments."""

    def slice_of(fact: _Fact) -> tuple[Any, ...]:
        return (fact.metric_id, fact.entity_id, fact.period, fact.unit, fact.currency)

    # A withheld row is a missing addend, not an absent one: summing without it
    # understates the breakdown and convicts its clean siblings. Only a
    # single-dimension row is ever an addend, so no other shape suppresses: a
    # multi-dimension row could never have been summed, and a withheld total is
    # either the group's only total -- `len(totals) != 1` skips it anyway -- or
    # a competitor to a surviving one, which is what `excluded_indices` exists
    # to unblock.
    suppressed = {slice_of(fact) for fact in withheld if len(fact.dimensions) == 1}
    groups: dict[tuple[Any, ...], list[_Fact]] = {}
    for fact in facts:
        key = slice_of(fact)
        if key in suppressed:
            continue
        groups.setdefault(key, []).append(fact)
    for group in groups.values():
        totals = [f for f in group if not f.dimensions]
        segments = [f for f in group if len(f.dimensions) == 1]
        if len(totals) != 1 or len(segments) < 2:
            continue
        # One dimension, each member distinct: otherwise the set is a partial
        # breakdown or a restatement, and summing it proves nothing.
        if len({f.dimensions[0][0] for f in segments}) != 1:
            continue
        if len({f.dimensions[0][1] for f in segments}) != len(segments):
            continue
        total = sum((f.magnitude for f in segments), Decimal("0"))
        if not relatively_equal(total, totals[0].magnitude):
            _record(out, [totals[0], *segments], f"{IDENTITY_PREFIX}segments_do_not_sum")


def _check_gross_profit(facts: list[_Fact], out: dict[int, list[str]]) -> None:
    """gross_profit = revenue − |cogs|, within one entity/period/currency slice.

    ``cogs`` is compared by magnitude, not by its signed value. This PR's own
    parenthesized-negative fix (normalize/numeric.py:135) makes the standard
    contra-account presentation for a cost line — 'Cost of revenue (300)' —
    parse to ``Decimal('-300')``: the parens there are a typesetting
    convention meaning "this reduces the total above", not a claim that the
    cost itself is a negative number. Comparing the signed value computes
    ``revenue - (-300) = revenue + 300``, which flags an entirely ordinary
    income statement as broken *and* would certify a doctored one where the
    reported gross profit exceeds revenue (PR #145 review B1).

    ``abs()`` is applied here, at comparison time only — not by having the
    normalizer rewrite the stored value or ``sign``. ``cogs.sign`` must keep
    describing the value exactly as extracted: ``normalize/payload.py``'s
    ``_resolve_sign`` derives it from that same signed value and is the thing
    that catches a genuinely mis-signed figure (a declared sign contradicting
    the parsed value). This function is the one place that knows COGS is
    always a subtraction from revenue, regardless of how the issuer chose to
    typeset it, so it is the right and only place to normalize the polarity.

    A COGS fact that is negative for a reason *other* than contra-presentation
    — a genuine net credit/reversal for the period, which does happen but is
    rare — is indistinguishable from ordinary parenthesized presentation using
    magnitude and sign alone; both look identical at this layer, and this
    function does not attempt that distinction. It folds every negative COGS
    the same way rather than guess.
    """
    groups: dict[tuple[Any, ...], list[_Fact]] = {}
    for fact in facts:
        if fact.metric_id in {_REVENUE_ID, _COGS_ID, _GROSS_PROFIT_ID}:
            groups.setdefault(_context(fact), []).append(fact)
    for group in groups.values():
        indexed = _by_metric(group)
        members = [_sole(indexed, name) for name in (_REVENUE_ID, _COGS_ID, _GROSS_PROFIT_ID)]
        if any(member is None for member in members):
            continue
        revenue, cogs, gross_profit = (m.magnitude for m in members if m is not None)
        if not relatively_equal(gross_profit, revenue - abs(cogs)):
            _record(
                out,
                [m for m in members if m is not None],
                f"{IDENTITY_PREFIX}gross_profit_mismatch",
            )


__all__ = [
    "IDENTITY_PREFIX",
    "IDENTITY_RELATIVE_TOLERANCE",
    "accounting_errors",
    "identity_errors",
    "relatively_equal",
]
