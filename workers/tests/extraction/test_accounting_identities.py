"""Cross-payload accounting identities and the per-payload rules folded in.

Before this, ``validate/accounting.py`` contained ``check_accounting`` with zero
call sites and no arithmetic identity at all, while its own docstring claimed
"margins, billings, RPO" and spec M3-VAL-001 required identities. These tests
pin both halves of the fix: the identities now exist and run on the live path,
and the rules that only lived in the dead function are now reached by
``accounting_errors``.

Numeric contract reminder: ``value`` is a mantissa and ``scale`` its decimal
exponent, so ``{"value": "1.2", "scale": 9}`` is $1.2bn. Several tests below
deliberately express the same magnitude at different scales.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fel_ontology import load_saas_metrics
from fel_workers.extraction.types import (
    NON_MAGNITUDE_NORMALIZER_BLOCKERS,
    NORMALIZER_BLOCKERS_KEY,
)
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.accounting import (
    IDENTITY_PREFIX,
    IDENTITY_RELATIVE_TOLERANCE,
    accounting_errors,
    identity_errors,
    relatively_equal,
)

ENTITY = "11111111-1111-4111-8111-111111111111"
SPAN = "22222222-2222-4222-8222-222222222222"
DOC = "33333333-3333-4333-8333-333333333333"
INSTANT = {"type": "instant", "instant": "2026-06-30", "fiscal_period": "FY2026-Q2"}
DURATION = {
    "type": "duration",
    "start": "2026-04-01",
    "end": "2026-06-30",
    "fiscal_period": "FY2026-Q2",
}


@pytest.fixture(scope="module")
def ontology():  # type: ignore[no-untyped-def]
    return load_saas_metrics()


def kpi(
    metric_id: str,
    value: str,
    *,
    scale: int = 0,
    unit: str = "USD",
    currency: str = "USD",
    period: dict[str, Any] | None = None,
    dimensions: dict[str, str] | None = None,
    qualifiers: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": ENTITY,
        "issuer_label": "Example SaaS",
        "metric_id": metric_id,
        "raw_value": f"{value}",
        "value": value,
        "unit": unit,
        "currency": currency,
        "scale": scale,
        "sign": "positive",
        "period": period if period is not None else INSTANT,
        "dimensions": dimensions or {},
        "definition": None,
        "qualifiers": qualifiers if qualifiers is not None else {},
        "reported_or_derived": "reported",
        "evidence": [{"source_span_id": SPAN, "document_version_id": DOC, "role": "supports"}],
    }
    payload.update(extra)
    return payload


def codes(result: dict[int, list[str]], index: int) -> list[str]:
    return result.get(index, [])


# --------------------------------------------------------------------------
# The tolerance is relative, not an absolute epsilon.
# --------------------------------------------------------------------------


def test_tolerance_is_relative_not_absolute() -> None:
    """One absolute gap, two magnitudes, two different verdicts.

    This is the property an absolute epsilon cannot have. The gap is exactly
    $1,000,000 in both pairs. Against $100m it is 1% — a real break. Against
    $100bn it is 0.001% — rounding in the issuer's own disclosure.
    """
    gap = Decimal("1000000")
    small = Decimal("100000000")
    large = Decimal("100000000000")

    assert not relatively_equal(small + gap, small)
    assert relatively_equal(large + gap, large)


def test_tolerance_verdict_is_scale_invariant() -> None:
    """The same *proportional* error is judged identically at any magnitude."""
    ratio = Decimal("1") + IDENTITY_RELATIVE_TOLERANCE * 2
    for magnitude in (Decimal("1"), Decimal("1000"), Decimal("1e9"), Decimal("1e12")):
        assert not relatively_equal(magnitude * ratio, magnitude)
        inside = Decimal("1") + IDENTITY_RELATIVE_TOLERANCE / 2
        assert relatively_equal(magnitude * inside, magnitude)


def test_zero_reference_requires_exact_equality() -> None:
    assert relatively_equal(Decimal("0"), Decimal("0"))
    assert not relatively_equal(Decimal("0.01"), Decimal("0"))


# --------------------------------------------------------------------------
# Identity: cRPO <= RPO
# --------------------------------------------------------------------------


def test_crpo_exceeding_rpo_is_flagged_on_both_members() -> None:
    result = identity_errors([kpi("rpo", "500"), kpi("crpo", "900")])
    assert codes(result, 0) == [f"{IDENTITY_PREFIX}crpo_exceeds_rpo"]
    assert codes(result, 1) == [f"{IDENTITY_PREFIX}crpo_exceeds_rpo"]


def test_crpo_below_rpo_is_clean() -> None:
    assert identity_errors([kpi("rpo", "900"), kpi("crpo", "500")]) == {}


def test_crpo_exceeding_rpo_is_caught_when_crpo_is_contra_presented() -> None:
    """A parenthesized cRPO must not slip past the balance check.

    Adversarial review of PR #145's B1 fix: `abs()` was applied to
    `_check_gross_profit` but not here, even though both read the same
    `_Fact.magnitude` and both became exposed by the same parens handling. Left
    signed, `-1500 > 1000` is false and a real violation -- a near-term portion
    half again the size of the whole backlog -- certified clean.
    """
    result = identity_errors([kpi("rpo", "1000"), kpi("crpo", "-1500", sign="negative")])
    assert codes(result, 0) == [f"{IDENTITY_PREFIX}crpo_exceeds_rpo"]
    assert codes(result, 1) == [f"{IDENTITY_PREFIX}crpo_exceeds_rpo"]

    # Same violation with both sides contra-presented.
    both = [kpi("rpo", "-1000", sign="negative"), kpi("crpo", "-1500", sign="negative")]
    assert codes(identity_errors(both), 1) == [f"{IDENTITY_PREFIX}crpo_exceeds_rpo"]


def test_crpo_exactly_equal_to_rpo_is_clean_in_every_sign_combination() -> None:
    """cRPO may legitimately equal RPO, in any combination of presented signs.

    When every remaining obligation falls inside the horizon, the near-term
    portion *is* the whole backlog, so an exact match is clean rather than a
    violation. No other test here ever feeds the identity two equal figures.

    The four sign combinations are the point. Mutation testing confirms this is
    the only test in the file that fails for **all three** ways the polarity fix
    can be undone -- dropping `abs()` entirely, and applying it to either side
    alone -- because the opposite-sign equal-magnitude pairs are exactly the
    inputs a half-applied `abs()` still gets wrong.

    Note for anyone tightening this: `>` vs `>=` on the size comparison is NOT
    what this test guards, and is not worth guarding. `and not
    relatively_equal(...)` already short-circuits an exact match, so the two
    operators are behaviourally identical here -- verified, not assumed.
    """
    for rpo_value, crpo_value, rpo_sign, crpo_sign in (
        ("1000", "1000", "positive", "positive"),
        ("1000", "-1000", "positive", "negative"),
        ("-1000", "1000", "negative", "positive"),
        ("-1000", "-1000", "negative", "negative"),
    ):
        payloads = [
            kpi("rpo", rpo_value, sign=rpo_sign),
            kpi("crpo", crpo_value, sign=crpo_sign),
        ]
        assert identity_errors(payloads) == {}, f"rpo={rpo_value} crpo={crpo_value}"


def test_contra_presented_rpo_does_not_spuriously_flag_a_valid_pair() -> None:
    """The other direction of the same defect: a valid pair must stay clean.

    Signed, `300 > -1000` is true, so a perfectly ordinary cRPO of 300 against
    an RPO of 1,000 was blocked for review. Comparing magnitudes asks the only
    question this identity is about -- is the portion bigger than the whole.
    """
    payloads = [kpi("rpo", "-1000", sign="negative"), kpi("crpo", "300")]
    assert identity_errors(payloads) == {}

    # And with both contra-presented.
    both = [kpi("rpo", "-1000", sign="negative"), kpi("crpo", "-300", sign="negative")]
    assert identity_errors(both) == {}


def test_segment_sums_keep_signed_magnitudes_and_are_not_abs_folded() -> None:
    """`_check_segment_sums` must NOT get the `abs()` treatment the other two need.

    A contra segment -- a returns or allowance line -- is legitimately negative,
    and the total is the net of its parts. `abs()`-ing the parts would compute
    1000 + 300 = 1300 against a correct total of 700 and block a correct filing.
    This pins the asymmetry so a future "consistency" cleanup cannot erase it.
    """
    correct = [
        kpi("arr", "700", dimensions={}),
        kpi("arr", "1000", dimensions={"segment": "gross"}),
        kpi("arr", "-300", sign="negative", dimensions={"segment": "allowance"}),
    ]
    assert identity_errors(correct) == {}

    broken = [
        kpi("arr", "750", dimensions={}),  # wrong: parts net to 700
        kpi("arr", "1000", dimensions={"segment": "gross"}),
        kpi("arr", "-300", sign="negative", dimensions={"segment": "allowance"}),
    ]
    assert codes(identity_errors(broken), 0) == [f"{IDENTITY_PREFIX}segments_do_not_sum"]


def test_crpo_rpo_compared_across_different_scales() -> None:
    """$1.2bn RPO vs $900m cRPO: comparing mantissas alone would read 1.2 < 900."""
    payloads = [kpi("rpo", "1.2", scale=9), kpi("crpo", "900", scale=6)]
    assert identity_errors(payloads) == {}

    # And the genuine break is still caught across mixed scales: $1.5bn cRPO
    # against $1.2bn RPO.
    broken = [kpi("rpo", "1200", scale=6), kpi("crpo", "1.5", scale=9)]
    assert codes(identity_errors(broken), 1) == [f"{IDENTITY_PREFIX}crpo_exceeds_rpo"]


def test_crpo_rpo_in_different_currencies_are_not_related() -> None:
    """Currency conversion is out of scope, so these are not one identity."""
    payloads = [kpi("rpo", "500", currency="USD"), kpi("crpo", "900", currency="EUR")]
    assert identity_errors(payloads) == {}


def test_crpo_rpo_in_different_periods_are_not_related() -> None:
    payloads = [
        kpi("rpo", "500"),
        kpi(
            "crpo",
            "900",
            period={"type": "instant", "instant": "2025-06-30", "fiscal_period": "FY2025-Q2"},
        ),
    ]
    assert identity_errors(payloads) == {}


def test_ambiguous_rpo_slice_is_left_to_conflict_detection() -> None:
    """Two competing RPO figures are a value disagreement, not a broken identity."""
    payloads = [kpi("rpo", "500"), kpi("rpo", "600"), kpi("crpo", "900")]
    assert identity_errors(payloads) == {}


def test_crpo_marginally_above_rpo_is_within_relative_tolerance() -> None:
    payloads = [kpi("rpo", "1000000000"), kpi("crpo", "1000001000")]
    assert identity_errors(payloads) == {}


# --------------------------------------------------------------------------
# Identity: segments sum to the reported total
# --------------------------------------------------------------------------


def test_segments_that_do_not_sum_flag_every_member() -> None:
    payloads = [
        kpi("arr", "1000"),
        kpi("arr", "400", dimensions={"segment": "enterprise"}),
        kpi("arr", "300", dimensions={"segment": "smb"}),
    ]
    result = identity_errors(payloads)
    assert set(result) == {0, 1, 2}
    assert all(c == [f"{IDENTITY_PREFIX}segments_do_not_sum"] for c in result.values())


def test_segments_that_sum_across_scales_are_clean() -> None:
    """$1.0bn total against $400m + $600m segments."""
    payloads = [
        kpi("arr", "1", scale=9),
        kpi("arr", "400", scale=6, dimensions={"segment": "enterprise"}),
        kpi("arr", "600", scale=6, dimensions={"segment": "smb"}),
    ]
    assert identity_errors(payloads) == {}


def test_rounded_segments_stay_within_relative_tolerance() -> None:
    """Three-significant-figure segments against a four-figure total."""
    payloads = [
        kpi("arr", "1000"),
        kpi("arr", "402", dimensions={"segment": "enterprise"}),
        kpi("arr", "601", dimensions={"segment": "smb"}),
    ]
    assert identity_errors(payloads) == {}


def test_partial_breakdown_over_two_dimensions_is_not_summed() -> None:
    """Mixed dimension names are not a partition, so summing proves nothing."""
    payloads = [
        kpi("arr", "1000"),
        kpi("arr", "400", dimensions={"segment": "enterprise"}),
        kpi("arr", "300", dimensions={"geography": "emea"}),
    ]
    assert identity_errors(payloads) == {}


def test_repeated_segment_value_is_not_summed() -> None:
    """A restatement of one segment is not a second segment."""
    payloads = [
        kpi("arr", "1000"),
        kpi("arr", "400", dimensions={"segment": "enterprise"}),
        kpi("arr", "410", dimensions={"segment": "enterprise"}),
    ]
    assert identity_errors(payloads) == {}


# --------------------------------------------------------------------------
# Identity: gross_profit = revenue - cogs
# --------------------------------------------------------------------------


def test_gross_profit_mismatch_flags_all_three() -> None:
    payloads = [
        kpi("revenue", "1000", period=DURATION),
        kpi("cogs", "300", period=DURATION),
        kpi("gross_profit", "600", period=DURATION),
    ]
    result = identity_errors(payloads)
    assert set(result) == {0, 1, 2}
    assert all(c == [f"{IDENTITY_PREFIX}gross_profit_mismatch"] for c in result.values())


def test_gross_profit_holds_across_scales() -> None:
    """$1.2bn revenue − $300m COGS = $900m gross profit."""
    payloads = [
        kpi("revenue", "1.2", scale=9, period=DURATION),
        kpi("cogs", "300", scale=6, period=DURATION),
        kpi("gross_profit", "0.9", scale=9, period=DURATION),
    ]
    assert identity_errors(payloads) == {}


def test_incomplete_gross_profit_triple_is_skipped() -> None:
    payloads = [kpi("revenue", "1000", period=DURATION), kpi("cogs", "300", period=DURATION)]
    assert identity_errors(payloads) == {}


# --------------------------------------------------------------------------
# Identity: gross_profit = revenue - cogs, contra-presented (negative) COGS
# --------------------------------------------------------------------------
# PR #145 review B1. This PR's own parenthesized-negative fix
# (normalize/numeric.py:135) makes a parenthesized COGS line -- '(300)', the
# standard contra-account presentation for a cost that reduces the total above
# it -- parse to Decimal('-300'). COGS is a cost; the parens are a
# presentation convention, not a claim that the cost itself is negative, so
# the identity must strip that polarity before subtracting. Left unstripped,
# `revenue - cogs` computes `revenue - (-300) = revenue + 300`, which flags an
# entirely ordinary income statement as broken *and* would certify a doctored
# one where the reported gross profit exceeds revenue.


def test_gross_profit_identity_accepts_contra_presented_cogs() -> None:
    """'Revenue 1,000 / Cost of revenue (300) / Gross profit 700' is correct."""
    payloads = [
        kpi("revenue", "1000", period=DURATION),
        kpi("cogs", "-300", period=DURATION, sign="negative"),
        kpi("gross_profit", "700", period=DURATION),
    ]
    assert identity_errors(payloads) == {}


def test_gross_profit_identity_still_catches_a_break_with_contra_presented_cogs() -> None:
    """Stripping COGS polarity must not make the identity pass unconditionally
    once cogs is negative -- a genuine break underneath is still caught.
    """
    payloads = [
        kpi("revenue", "1000", period=DURATION),
        kpi("cogs", "-300", period=DURATION, sign="negative"),
        kpi("gross_profit", "1300", period=DURATION),
    ]
    result = identity_errors(payloads)
    assert set(result) == {0, 1, 2}
    assert all(c == [f"{IDENTITY_PREFIX}gross_profit_mismatch"] for c in result.values())


# --------------------------------------------------------------------------
# Identity slice matching and `unit` case: a known gap, deliberately pinned
# --------------------------------------------------------------------------
# PR #145 review M2 observed that normalize/payload.py:148 upper-cases
# `currency` while line 142 leaves `unit` exactly as the issuer wrote it, so
# 'usd' and 'USD' key different slices in `_context` and an identity spanning
# both is skipped rather than checked. That observation is correct and the gap
# is real -- issue #153 owns it.
#
# Case-folding in `_facts` alone was tried here and REVERTED, because it makes
# the system worse: `duplicates.comparability_key_for` does not fold, so
# folding one side breaks the handoff `_sole` depends on. The two tests below
# pin both halves of that reasoning so neither can be undone by accident.


def test_gross_profit_identity_skips_across_unit_casing_known_gap() -> None:
    """Pins the KNOWN GAP that issue #153 owns: unit case splits the slice.

    This asserts today's failing-open behaviour on purpose. When #153 lands a
    consistent unit policy this test SHOULD fail -- update it then rather than
    silencing it, and make sure the duplicate/conflict side folds too.
    """
    payloads = [
        kpi("revenue", "1000", period=DURATION, unit="USD"),
        kpi("cogs", "300", period=DURATION, unit="usd"),
        kpi("gross_profit", "600", period=DURATION, unit="USD"),  # wrong: should be 700
    ]
    assert identity_errors(payloads) == {}


def test_unit_case_split_still_lets_a_break_be_caught_in_its_own_slice() -> None:
    """Why folding in `_facts` alone was reverted, not just deferred.

    Two `revenue` rows for one economic quantity differing only in unit case --
    a duplicate extraction from two spans of the same filing. Unfolded, they sit
    in separate slices, so the 'USD' slice holds exactly one revenue and the
    genuine gross-profit break IS caught.

    Folding only `_facts` merged them into one slice, `_sole` backed off to
    `validate.conflicts` as designed, and conflicts -- still keyed on the
    unfolded unit via `comparability_key_for` -- never saw the pair. The break
    then disappeared with no blocker from any checker at all, strictly worse
    than the gap above. If this test ever starts returning `{}`, a one-sided
    fold has been reintroduced.
    """
    payloads = [
        kpi("revenue", "1000", period=DURATION, unit="USD"),
        kpi("revenue", "1000", period=DURATION, unit="usd"),
        kpi("cogs", "400", period=DURATION, unit="USD"),
        kpi("gross_profit", "700", period=DURATION, unit="USD"),  # wrong: 1000-400=600
    ]
    result = identity_errors(payloads)
    assert set(result) == {0, 2, 3}
    assert all(c == [f"{IDENTITY_PREFIX}gross_profit_mismatch"] for c in result.values())


# --------------------------------------------------------------------------
# A normalizer-rejected sibling must not disable an identity for clean facts
# --------------------------------------------------------------------------
# PR #145 review M1. `_sole` correctly backs off an identity when a slice holds
# two competing facts for the same metric -- that is a value disagreement
# `validate.conflicts` owns, not a broken identity. But a row the normalizer
# itself already rejected is not a competing fact, it is noise the pipeline
# decided not to trust; left in, it looks exactly like a second competing fact
# to `_sole`, and the identity silently switches off for every clean sibling
# sharing its slice too.


def test_identity_errors_excludes_indices_marked_normalizer_rejected() -> None:
    payloads = [
        kpi("revenue", "1000", period=DURATION),
        kpi("cogs", "300", period=DURATION),
        kpi("gross_profit", "600", period=DURATION),  # deliberately wrong: should be 700
        kpi("cogs", "999", period=DURATION),  # a second "cogs" fact in the same slice
    ]
    # Without exclusion, two "cogs" facts in one slice make `_sole` ambiguous
    # and the whole gross-profit identity is silently skipped -- the bug.
    assert identity_errors(payloads) == {}

    result = identity_errors(payloads, excluded_indices=frozenset({3}))
    assert set(result) == {0, 1, 2}
    assert all(c == [f"{IDENTITY_PREFIX}gross_profit_mismatch"] for c in result.values())


# --------------------------------------------------------------------------
# A cosmetic normalizer blocker must not withdraw an identity
# --------------------------------------------------------------------------
# `NORMALIZER_BLOCKERS_KEY` was built to carry scale/sign contradictions --
# findings that make a row's NUMBER untrustworthy, so dropping it from the
# arithmetic is right. #162 routed two advisories onto the same key that say
# nothing about the number. `validate/pipeline.py` excluded on mere presence,
# so one of those silently withdrew a check `main` performs.


def test_a_cosmetic_normalizer_blocker_does_not_withdraw_an_accounting_identity() -> None:
    """cRPO $900m against RPO $500m is arithmetically impossible either way.

    It went entirely unreported because one dimension value arrived as `12`
    rather than `"12"`: `dimensions_non_string` landed on the blockers key,
    `validate/pipeline.py` marked the row normalizer-rejected, and
    `identity_errors` dropped it from `_check_rpo_balance`. The reviewer saw a
    cosmetic typing note on the cRPO row and a completely clean RPO row.

    Both codes must survive together -- the advisory AND the arithmetic.
    """
    for cosmetic in ("dimensions_non_string", "currency_missing_for_monetary"):
        crpo = kpi(
            "crpo",
            "900",
            qualifiers={"currency": "USD", "horizon_months": "12"},
            dimensions={"horizon": "12m"},
        )
        crpo[NORMALIZER_BLOCKERS_KEY] = [cosmetic]
        result = validate_proposals(
            run_id="00000000-0000-4000-8000-0000000000c1",
            payloads=[
                kpi(
                    "rpo",
                    "500",
                    qualifiers={
                        "currency": "USD",
                        "usage_exemption": "none",
                        "label_family": "rpo",
                    },
                ),
                crpo,
            ],
        )
        blockers = [
            blocker
            for proposal in result.proposals
            for blocker in proposal.validation_summary.get("blockers", [])
        ]
        assert f"{IDENTITY_PREFIX}crpo_exceeds_rpo" in blockers, cosmetic
        assert cosmetic in blockers, cosmetic


def test_a_magnitude_normalizer_blocker_still_withdraws_the_row() -> None:
    """The other direction, so the fix above cannot be "stop excluding at all".

    A declared sign that contradicts the value means the row's magnitude is
    not established. Arithmetic over it is meaningless, and a row like that
    also looks to `_sole` exactly like a second competing fact -- the PR #145
    review M1 contract. This must keep excluding.
    """
    crpo = kpi(
        "crpo",
        "900",
        qualifiers={"currency": "USD", "horizon_months": "12"},
        dimensions={"horizon": "12m"},
    )
    crpo[NORMALIZER_BLOCKERS_KEY] = ["sign contradicts value: declared positive, value is negative"]
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000c2",
        payloads=[
            kpi(
                "rpo",
                "500",
                qualifiers={
                    "currency": "USD",
                    "usage_exemption": "none",
                    "label_family": "rpo",
                },
            ),
            crpo,
        ],
    )
    blockers = [
        blocker
        for proposal in result.proposals
        for blocker in proposal.validation_summary.get("blockers", [])
    ]
    assert f"{IDENTITY_PREFIX}crpo_exceeds_rpo" not in blockers


def test_every_normalizer_blocker_code_is_deliberately_classified() -> None:
    """A new stable blocker code must be classified, not defaulted into gating.

    The default is "this blocker withdraws the row from the identities", which
    is correct for a magnitude finding and wrong for an advisory -- that
    default is exactly how the cRPO regression above shipped. Scanning for the
    literals the normalizer appends makes the next omission a test failure
    rather than a silently withdrawn accounting check.

    Only stable identifier codes are scanned. The scale/sign findings are
    interpolated sentences, not literals, and they gate by design.
    """
    normalize_dir = Path(__file__).resolve().parents[2] / "src" / "fel_workers"
    normalize_dir = normalize_dir / "extraction" / "normalize"
    found: set[str] = set()
    for module in sorted(normalize_dir.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "append":
                continue
            target = node.func.value
            if not isinstance(target, ast.Name) or target.id != "blockers":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)

    assert found, "scan found no blocker literals -- the scan itself has rotted"
    unclassified = found - set(NON_MAGNITUDE_NORMALIZER_BLOCKERS)
    assert unclassified == set(), (
        f"normalizer blocker code(s) {sorted(unclassified)} are not classified in "
        "NON_MAGNITUDE_NORMALIZER_BLOCKERS. Decide deliberately: does this finding "
        "impugn the row's magnitude (leave it out, it gates the accounting "
        "identities) or not (add it)?"
    )


# --------------------------------------------------------------------------
# Identities reach the live validate path.
# --------------------------------------------------------------------------


def test_identity_violation_reaches_the_proposal_draft() -> None:
    """The regression that mattered: identities used to have no call site."""
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a1",
        payloads=[
            kpi(
                "rpo",
                "500",
                qualifiers={
                    "currency": "USD",
                    "usage_exemption": "none",
                    "label_family": "rpo",
                },
            ),
            kpi(
                "crpo",
                "900",
                qualifiers={"currency": "USD", "horizon_months": "12"},
                dimensions={"horizon": "12m"},
            ),
        ],
    )
    assert len(result.proposals) == 2
    for draft in result.proposals:
        blockers = draft.validation_summary["blockers"]
        assert f"{IDENTITY_PREFIX}crpo_exceeds_rpo" in blockers
        assert draft.validation_summary["ok"] is False
        assert draft.state == "needs_review"


def test_clean_slice_carries_no_identity_blocker() -> None:
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a2",
        payloads=[
            kpi(
                "rpo",
                "900",
                qualifiers={
                    "currency": "USD",
                    "usage_exemption": "none",
                    "label_family": "rpo",
                },
            ),
            kpi(
                "crpo",
                "500",
                qualifiers={"currency": "USD", "horizon_months": "12"},
                dimensions={"horizon": "12m"},
            ),
        ],
    )
    for draft in result.proposals:
        assert not [b for b in draft.validation_summary["blockers"] if IDENTITY_PREFIX in b]


def test_normalizer_rejected_sibling_does_not_disable_identity_for_clean_rows() -> None:
    """PR #145 review M1, reproduced end-to-end through the real pipeline.

    Four proposals reach ``validate_proposals``: a clean revenue/cogs/gross_profit
    triple with a deliberately wrong gross profit, plus a fourth "cogs" payload
    the normalizer already rejected (carrying ``NORMALIZER_BLOCKERS_KEY``, the
    channel ``workflow._stage_normalize`` uses to carry a rejected payload
    forward for review rather than dropping it silently). ``pipeline.py``
    strips that `_`-prefixed key into ``clean`` before appending to
    ``cleaned_payloads`` (so schema validation and persistence never see it),
    which is exactly the mechanism that let a rejected duplicate masquerade as
    a second competing "cogs" fact and switch the identity off for its three
    clean siblings.
    """
    payloads = [
        kpi("revenue", "1000", period=DURATION),
        kpi("cogs", "300", period=DURATION),
        kpi("gross_profit", "600", period=DURATION),  # deliberately wrong: should be 700
    ]
    rejected_duplicate_cogs = kpi("cogs", "999", period=DURATION)
    rejected_duplicate_cogs[NORMALIZER_BLOCKERS_KEY] = [
        "sign contradicts value: declared positive, value is negative"
    ]

    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a6",
        payloads=[*payloads, rejected_duplicate_cogs],
    )
    assert len(result.proposals) == 4

    def identity_blockers(draft: Any) -> list[str]:
        return [b for b in draft.validation_summary["blockers"] if IDENTITY_PREFIX in b]

    for draft in result.proposals[:3]:
        assert identity_blockers(draft) == [f"{IDENTITY_PREFIX}gross_profit_mismatch"]
    assert identity_blockers(result.proposals[3]) == []


# --------------------------------------------------------------------------
# Percent bounds: scale-aware, and every spelling of the unit.
# --------------------------------------------------------------------------


def test_percent_bound_reads_the_scaled_magnitude(ontology) -> None:  # type: ignore[no-untyped-def]
    """``{"value": "1.5", "scale": 3}`` is 1500%, not 1.5%."""
    payload = kpi(
        "nrr",
        "1.5",
        scale=3,
        unit="percent",
        qualifiers={"base_quantity": "arr", "window": "ttm", "population_scope": "all"},
    )
    errors = accounting_errors(payload, ontology)
    assert any("out of plausible range" in e for e in errors)
    assert any("scale 0" in e for e in errors)


def test_percent_bound_ignores_scale_zero(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = kpi(
        "nrr",
        "118",
        unit="percent",
        qualifiers={"base_quantity": "arr", "window": "ttm", "population_scope": "all"},
    )
    assert accounting_errors(payload, ontology) == []


@pytest.mark.parametrize("unit", ["percent", "%", "pct", "Percent", " PCT ", "percentage"])
def test_margin_bound_matches_every_spelling_of_percent(ontology, unit: str) -> None:  # type: ignore[no-untyped-def]
    """Exact ``unit == "percent"`` used to skip "%" and "pct" entirely."""
    payload = kpi(
        "sub_gm",
        "180",
        unit=unit,
        qualifiers={"margin_scope": "subscription"},
    )
    assert "margin_percent_out_of_range" in accounting_errors(payload, ontology)


def test_margin_bound_skips_a_non_percent_unit(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = kpi("sub_gm", "180", unit="bps", qualifiers={"margin_scope": "subscription"})
    errors = accounting_errors(payload, ontology)
    assert "margin_percent_out_of_range" not in errors


def test_percent_bound_covers_guidance_low_and_high(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = {
        "kind": "guidance",
        "metric_id": "sub_gm",
        "shape": "range",
        "unit": "%",
        "low": "70",
        "high": "9000",
        "scale": 0,
        "qualifiers": {"margin_scope": "subscription"},
    }
    errors = accounting_errors(payload, ontology)
    assert any("out of plausible range: 9000" in e for e in errors)


# --------------------------------------------------------------------------
# Rules that only existed in the dead check_accounting now run on the live path.
# --------------------------------------------------------------------------


def test_dead_function_is_gone() -> None:
    from fel_workers.extraction.validate import accounting

    assert not hasattr(accounting, "check_accounting")


def test_billings_derivation_lineage_is_required(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = kpi(
        "billings",
        "100",
        qualifiers={"currency": "USD", "formula": "revenue + delta_deferred"},
        reported_or_derived="derived",
    )
    assert "billings_derivation_inputs_missing" in accounting_errors(payload, ontology)

    with_lineage = kpi(
        "billings",
        "100",
        qualifiers={
            "currency": "USD",
            "formula": "revenue + delta_deferred",
            "derivation_inputs": ["revenue", "deferred_rev"],
        },
        reported_or_derived="derived",
    )
    assert accounting_errors(with_lineage, ontology) == []


def test_crpo_timing_must_be_verified(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = kpi("crpo", "100", qualifiers={"currency": "USD", "horizon_months": "12"})
    assert "crpo_timing_unverified" in accounting_errors(payload, ontology)

    verified = kpi(
        "crpo",
        "100",
        qualifiers={"currency": "USD", "horizon_months": "12"},
        dimensions={"horizon": "12m"},
    )
    assert accounting_errors(verified, ontology) == []


def test_svc_gm_blended_basis_is_forbidden(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = kpi(
        "svc_gm",
        "40",
        unit="percent",
        qualifiers={"margin_scope": "professional_services", "basis": "blended"},
    )
    assert "svc_gm_blended_forbidden" in accounting_errors(payload, ontology)


def test_svc_gm_blended_scope_is_forbidden(ontology) -> None:  # type: ignore[no-untyped-def]
    payload = kpi("svc_gm", "40", unit="percent", qualifiers={"margin_scope": "consolidated"})
    errors = accounting_errors(payload, ontology)
    assert any("blended company gross margin" in e for e in errors)


def test_live_path_reports_billings_lineage_blocker() -> None:
    """The dead function's rules must be reachable from validate_proposals."""
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a3",
        payloads=[
            kpi(
                "billings",
                "100",
                qualifiers={"currency": "USD", "formula": "revenue + delta_deferred"},
                reported_or_derived="derived",
            )
        ],
    )
    assert (
        "billings_derivation_inputs_missing" in result.proposals[0].validation_summary["blockers"]
    )


def _sum_breaks(draft: Any) -> list[str]:
    return [b for b in draft.validation_summary["blockers"] if "segments_do_not_sum" in b]


def test_a_withheld_segment_does_not_fabricate_a_sum_break_for_its_clean_siblings() -> None:
    """The mirror image of the PR #145 review M1 case above.

    There, a normalizer-rejected row had to be dropped so a *comparison*
    identity could still run for its clean siblings. An *aggregation* is the
    opposite: a dropped row is a missing addend, not an absent competitor.

    100 against segments of 50 + 30 + 20 balances exactly. Withhold the 20 and
    the survivors sum to 80, which still satisfies every precondition
    ``_check_segment_sums`` tests -- so it convicts the three rows that are
    individually correct of a shortfall that is purely an artefact of the
    exclusion, while the withheld row itself is flagged with nothing.
    """
    total = kpi("arr", "100", period=DURATION)
    emea = kpi("arr", "50", period=DURATION, dimensions={"segment": "emea"})
    apac = kpi("arr", "30", period=DURATION, dimensions={"segment": "apac"})
    amer = kpi("arr", "20", period=DURATION, dimensions={"segment": "amer"})
    amer[NORMALIZER_BLOCKERS_KEY] = ["dimensions_non_string"]

    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a7",
        payloads=[total, emea, apac, amer],
    )

    assert len(result.proposals) == 4
    for draft in result.proposals:
        assert _sum_breaks(draft) == []


def test_suppressing_one_slice_does_not_silence_a_real_break_in_another() -> None:
    """Withholding is scoped to the slice that lost a member.

    Without this, the fix for the case above could be satisfied by disabling
    the segment-sum identity globally whenever any row is withheld. The ``arr``
    slice here has a withheld segment and must stay silent; the ``revenue``
    slice is entirely clean, genuinely does not sum (50 + 30 != 100), and must
    still report.
    """
    withheld_slice = [
        kpi("arr", "100", period=DURATION),
        kpi("arr", "50", period=DURATION, dimensions={"segment": "emea"}),
        kpi("arr", "30", period=DURATION, dimensions={"segment": "apac"}),
        kpi("arr", "20", period=DURATION, dimensions={"segment": "amer"}),
    ]
    withheld_slice[3][NORMALIZER_BLOCKERS_KEY] = ["dimensions_non_string"]
    broken_slice = [
        kpi("revenue", "100", period=DURATION),
        kpi("revenue", "50", period=DURATION, dimensions={"segment": "emea"}),
        kpi("revenue", "30", period=DURATION, dimensions={"segment": "apac"}),
    ]

    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a8",
        payloads=[*withheld_slice, *broken_slice],
    )

    arr_rows, revenue_rows = result.proposals[:4], result.proposals[4:]
    assert [_sum_breaks(draft) for draft in arr_rows] == [[], [], [], []]
    assert all(_sum_breaks(draft) for draft in revenue_rows)


def test_a_withheld_multi_dimension_row_does_not_silence_a_real_break() -> None:
    """Over-suppression, the direction the two tests above do not cover.

    ``_check_segment_sums`` only ever sums single-dimension segments against a
    zero-dimension total, so a row carrying two dimensions is inert: it can
    never be an addend, and withholding it removes nothing from the sum. Keyed
    on ``(metric_id, entity_id, period, unit, currency)`` alone, though, it
    suppressed the whole slice -- and 400 + 300 against a reported 1,000 went
    unreported for three rows the exclusion never touched.
    """
    payloads = [
        kpi("arr", "1000"),
        kpi("arr", "400", dimensions={"segment": "enterprise"}),
        kpi("arr", "300", dimensions={"segment": "smb"}),
        kpi("arr", "250", dimensions={"segment": "enterprise", "geography": "emea"}),
    ]
    # The multi-dimension row changes nothing while it is present, which is the
    # whole point: withholding it must not change anything either.
    assert set(identity_errors(payloads)) == {0, 1, 2}

    result = identity_errors(payloads, excluded_indices=frozenset({3}))
    assert set(result) == {0, 1, 2}
    assert all(c == [f"{IDENTITY_PREFIX}segments_do_not_sum"] for c in result.values())


def test_a_withheld_total_does_not_silence_a_break_against_the_surviving_total() -> None:
    """Why the suppression filter is ``== 1`` and not ``<= 1``.

    A zero-dimension row is the sum's target, never one of its addends, so
    withholding one cannot understate the breakdown. Suppressing on it is
    either redundant -- when it was the group's only total, ``len(totals) != 1``
    skips the group regardless -- or actively wrong, as here: the rejected row
    is a second, competing total, and leaving it to gate the check is the exact
    "a rejected sibling silently disables the identity for its clean rows"
    failure ``excluded_indices`` was added to end.
    """
    payloads = [
        kpi("arr", "900"),  # normalizer-rejected, and not the total to trust
        kpi("arr", "1000"),
        kpi("arr", "400", dimensions={"segment": "enterprise"}),
        kpi("arr", "300", dimensions={"segment": "smb"}),
    ]
    # Two totals in one slice is ambiguous, so the check backs off entirely.
    assert identity_errors(payloads) == {}

    result = identity_errors(payloads, excluded_indices=frozenset({0}))
    assert set(result) == {1, 2, 3}
    assert all(c == [f"{IDENTITY_PREFIX}segments_do_not_sum"] for c in result.values())
