# Cherry-pick study: FinRobot valuation engine → FEL calculation-engine

**Status:** Proposal / research draft (NOT an accepted ADR)
**Date:** 2026-07-20 (rev 6 — identity encoding decision: out-of-alphabet None marker in sketch; typed canonical JSON mandatory for real port)
**Author:** multi-agent analysis session (`claude/finrobot-multi-agent-analysis-fd6byx`)
**Companion:** `finrobot-cherry-pick-extraction-agents.md` (same treatment for the M3 extraction roles).
**Scope guard:** Illustrative code only — no source is added under `packages/calculation-engine/**`.
`packages/calculation-engine/**` is an `M4-MODEL-CALC` `allowed_path`
(`docs/handoff/workstreams.yaml`; tasks {T0401, T0402, T0403, T0409, T0410}, calc engine per
T0403; the path is shared with the sibling `M4-FACT-SCENARIOS` workstream, not exclusive to
`M4-MODEL-CALC`), **not** an AGENTS.md shared path. So the engine's *internal* source lands as normal work under the M4
issue. An accepted ADR + `contract-change` label is required only when a **shared path** is
touched: publishing the engine's public types into `packages/contracts/`, adding a migration
under `db/migrations/`, or — for §8 of this doc — amending `specs/001-financial-evidence-lab/`
(the `specs/` tree is a shared path). This study lives in `docs/research/` (not a shared
path) precisely so it needs neither.

## 1. What was studied

Source: `AI4Finance-Foundation/FinRobot` at commit
`297a8d28d099be328c8a8eb658b4f782b93f3651` (Apache-2.0 per the repository LICENSE; its
`setup.py` inconsistently says MIT),
`finrobot_equity/core/src/modules/valuation_engine.py` (420 lines) — a pure-Python, LLM-free
`ValuationEngine` computing EV/EBITDA, peer-comparison, and simplified DCF valuations, then
exposing `generate_football_field_data()` (per-method `{low, mid, high}` ranges),
`synthesize_valuation()` (confidence-weighted blend), and `explain_valuation_differences()`.

Its principle — **"deterministic numbers in code, LLM only narrates"** — is exactly FEL
Constitution **Principle II** (*"Authoritative monetary calculations MUST use decimal
arithmetic, typed units, explicit fiscal periods, and deterministic formulas. Language models
MAY propose or explain assumptions but MUST NOT execute authoritative financial math."*). That
alignment is why it is worth studying. What follows is not a drop-in — it is a rewrite under
FEL's invariants, with the donor's shortcuts enumerated so the cost of compliance is explicit.

## 2. Scope reality check

FEL's MVP (`specs/001-financial-evidence-lab/spec.md` §3, non-goal §4.2) is **revenue and
gross-profit driver modeling only** — no three-statement model, no DCF, no valuation, no price
targets. So FinRobot's DCF/EV-EBITDA *math is out of MVP scope*. What transfers is the **engine
pattern**, not the valuation formulas:

| Transferable at M4 | Deferred to P1 (see §8) | **Rejected** |
|---|---|---|
| Deterministic calc primitive with typed inputs/outputs | DCF / WACC / terminal value | Confidence-weighted multi-method synthesis |
| Every input carries source-span lineage + provenance kind | EV/EBITDA & peer-multiple valuation | Autonomous agent-to-agent orchestration |
| `{low, mid, high}` range → waterfall / tornado / sensitivity-heatmap viz (spec §8.5) | "Football field" chart (per-method ranges side by side) | |
| Versioned formula id + deterministic, content-addressed result id | | |

**Why synthesis is rejected, not deferred:** FinRobot blends methods by hard-coded confidence
weights (`0.7/0.6/0.5`) into one headline target price. Blending by opaque weights *hides* the
inter-method disagreement that FEL's "visible reasoning" thesis exists to show. The FEL-native
presentation is per-method `Range`s side by side (which is literally what a football-field
chart is), letting the analyst weight explicitly — or, if a machine weight is ever needed, the
versioned `isotonic-v1` calibrator already frozen in ADR-0007. A weighted single number is the
"opaque chat answer as terminal experience" the spec forbids, in numeric form.

## 3. Compliance gaps — FinRobot shortcuts vs. FEL invariants

The real value of the study: what "FEL-compliant" costs relative to the donor.

| # | FinRobot code | FEL invariant violated | Required fix |
|---|---|---|---|
| G1 | `float` throughout (`target_price: float`, `ebitda * multiple`) | Constitution II: decimal arithmetic; spec §11.4 "no binary float for money" | `Decimal` end-to-end, constructed from strings; runtime type + finiteness guard |
| G2 | `net_debt = ev * 0.1`, `fcf = ebitda * 0.6` — silent magic numbers (and `net_debt = 0.1·EV` is *definitionally circular*: EV ≡ equity + net debt, so this is just a flat 10% haircut) | Provenance: reported/derived/assumption/forecast must stay distinguishable (Constitution II; spec §11.4) | Every non-sourced number is an explicit typed `Assumption` with an id, temporal stamp, and unit — never inline |
| G3 | Inputs are bare dict lookups (`financial_data.get('ebitda', 0)`) | Lineage chain `source → span → fact → assumption → formula → forecast` (spec §11.4, §11.3) | Each input carries exactly one lineage field matched to its kind: `source_span_id` (REPORTED), `assumption_id` (ASSUMPTION), or `derived_from` (DERIVED) |
| G4 | `confidence=0.7` hard-coded, then used as blend weight in `synthesize_valuation` | Deterministic, versioned formulas | Rejected outright (§2); calibrated confidence only via `isotonic-v1` (ADR-0007) |
| G5 | No temporal stamping; reads "latest" column blindly | Constitution I: a calc at cutoff T sees only evidence public ≤ T (backtests too) | Every input carries `as_of`; engine refuses any input newer than the run cutoff |
| G6 | `except:` swallow-all returning `0` | Test-first / fail-closed | Typed errors; a missing required input raises, never silently `0` |
| G7 | No result identity | Deterministic content-addressed IDs (cf. `packages/retrieval/fel_retrieval/ids.py`) | Sketch: `result_id = UUIDv5(formula_version \| joined SAFE_ID inputs)` with an out-of-alphabet None marker so joins stay injective. **Real port MUST** hash typed canonical JSON (`null` ≠ `"-"`; enums for unit axes) and carry adversarial collision tests — string joins are illustrative only |
| G8 | Mutable `self.valuation_results` accumulator | Immutable, reproducible artifacts | Pure functions returning frozen dataclasses |
| G9 | Terminal value `fcf·(1+g)/(wacc−g)` with no guard | Fail-closed math | P1 DCF must reject `wacc ≤ terminal_growth` (incl. the ±1% band shifts) before dividing |
| G10 | No fiscal-period typing — values are addressed by spreadsheet-style year columns (`'2024A'`, `'2025E'`) | Constitution II: **explicit fiscal periods**; publication time (`as_of`) and measured period are different timelines | Every quantity carries a `FiscalPeriod(start, end)`; formulas validate period consistency *between* inputs and derive output periods, never leaving them implicit in a metric name |
| G11 | `_get_metric` strips `%` without dividing by 100 — latent 100× error for any rate metric | Constitution II: typed units | A dimensionless bucket is not enough: `Unit` carries a `measure` axis so a ratio, a count, and an (ingestion-normalized) percent are structurally distinct |

## 4. FEL-compliant port skeleton (illustrative — rev 3, hardened after two review passes)

House style mirrored from `packages/retrieval/fel_retrieval/` and
`packages/providers/fel_providers/interfaces.py`. Import package name follows the `fel_<dir>`
norm: dir `calculation-engine` → package `fel_calculation_engine`. UUIDv5 id logic lives in a
dedicated `ids.py` (mirroring `fel_retrieval/ids.py`).

Rev 3 changes vs. rev 2 (from the second adversarial pass): correct calendar-quarter month
arithmetic in `next_quarter` (rev 2 cloned the prior period's *day count*, drifting ~5
days/year — measured, not hypothetical); period-consistency and quarterly-unit enforcement
between inputs; slug-validated lineage ids + UTC-normalized timestamps so the content address
is injective and canonical (the house reason `fel_retrieval/ids.py` can join with `|` is that
its components are delimiter-free tokens — free strings forge delimiters); **exactly-one** lineage field
per provenance kind, selected by kind rather than `or`-chains; a `measure` axis on `Unit`
(ratio ≠ count; blocks the donor's 100× percent bug, G11); finiteness guards (NaN/Inf
`Decimal`s otherwise slip through sign checks); `AssumptionSet` invariants enforced;
`CalcResult` self-validation.

```python
# packages/calculation-engine/fel_calculation_engine/models.py  (PROPOSED — not committed as source)
"""Typed inputs/outputs for the deterministic calculation engine.

Constitution II: authoritative math is decimal, typed-unit, explicit-fiscal-period, versioned,
deterministic. No LLM. Every quantity carries EXACTLY ONE lineage field matched to its
provenance kind. NOTE for a real port: this `Provenance` sketch must be reconciled with the
frozen data model before adoption — spec §11.4 `NormalizedFinancialFact.reported_or_derived`
(binary flag + source_span_id) and the §11.3 closed claim-state set — and with Constitution
II's four-way reported/derived/user-supplied/forecast distinction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

# Money rounding policy: ROUND_HALF_EVEN (banker's, unbiased) at MONEY_SCALE. Cents are a
# USD placeholder — a real port derives the quantum from ISO 4217 minor units (JPY=0, KWD=3)
# keyed by Unit.currency, and quantizes only at graph edges so rounding never compounds
# node-to-node through DERIVED quantities.
MONEY_SCALE = Decimal("0.01")

# Lineage ids and formula versions must be slugs/UUIDs so joined identity keys are injective.
# This is WHY fel_retrieval/ids.py can join with "|": its components are delimiter-free
# tokens (slugs/UUIDs) and cannot contain delimiters. Free-form ids would let "a;b" forge a boundary.
# Keep "-" in the alphabet: UUID lineage ids are hyphenated. Do NOT "fix" None-collisions
# by banning "-" from SAFE_ID — encode absent Unit fields with a marker OUTSIDE this set.
SAFE_ID = re.compile(r"^[A-Za-z0-9._@-]+$")


def _require_safe_id(value: str, field: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must match {SAFE_ID.pattern!r}, got {value!r}")
    return value


def _require_decimal(value: object, field: str) -> Decimal:
    # Reject float outright (Constitution II); reject non-finite Decimals too — NaN passes
    # `<= 0` sign checks silently and Infinity survives until quantize().
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field} must be finite, got {value}")
    return value


def _canon_decimal(value: Decimal) -> str:
    canon = format(value.normalize(), "f")   # 0.10 / 0.1000 / 1E-1 → one representation
    return "0" if canon == "-0" else canon   # Decimal("-0.00") normalizes to "-0"


def _utc_key(ts: datetime) -> str:
    # 12:00Z and 14:00+02:00 are the same instant; canonicalize before hashing.
    return ts.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Unit:
    """Structured unit. The `measure` axis separates dimensionless kinds the donor conflated:
    a growth *ratio* is not a share *count*, and percents are normalized to fractions at
    ingestion (the donor's strip-'%'-without-/100 bug, G11, is exactly this hole)."""
    currency: str | None = None      # ISO 4217 ("USD"); real port validates against the table
    per_period: str | None = None    # "quarter" | "year" | None — an Enum in a real port
    measure: str | None = None       # "ratio" | "count" | None (currency amounts)

    def __post_init__(self) -> None:
        # Components enter joined identity keys, so they must be delimiter-free tokens —
        # otherwise Unit(None, "A/B", "C") and Unit(None, "A", "B/C") collide to one key
        # and memoization can return the wrong financial result (verified collision).
        for f in ("currency", "per_period", "measure"):
            v = getattr(self, f)
            if v is not None and not SAFE_ID.fullmatch(v):
                raise ValueError(f"Unit.{f} must match {SAFE_ID.pattern!r}, got {v!r}")
        if self.currency is not None and self.measure is not None:
            raise ValueError("currency amounts must not also declare a measure")

    def key(self) -> str:
        # Option A (sketch): None → marker OUTSIDE SAFE_ID (NUL). A present "-" is still a
        # legal token (UUIDs need hyphens in SAFE_ID), so encoding None as "-" would collide
        # Unit(None,None,None) with Unit("-","-","-"). Option C (real port MUST): do not join —
        # hash typed canonical JSON where missing axes are JSON null, not a sentinel string.
        parts = (self.currency, self.per_period, self.measure)
        return "/".join(p if p is not None else "\x00" for p in parts)


RATIO = Unit(measure="ratio")


@dataclass(frozen=True)
class FiscalPeriod:
    """The span a value MEASURES — distinct from `as_of` (when it became public). Closes G10."""
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("fiscal period start after end")

    def next_quarter(self) -> FiscalPeriod:
        # Calendar-quarter MONTH arithmetic. (Rev 2 cloned the prior period's day count,
        # which drifts ~5 days/year — Q1 2026 advanced four times landed on Dec 27.)
        # Still illustrative: a real port must use the issuer's fiscal calendar from
        # ingested facts (4-4-5 calendars, 53-week years, non-January fiscal years).
        start = self.end + timedelta(days=1)
        y, m = divmod(start.month - 1 + 3, 12)   # first day of the month AFTER the quarter
        end = date(start.year + y, m + 1, 1) - timedelta(days=1)
        return FiscalPeriod(start=start, end=end)

    def key(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


class Provenance(str, Enum):
    REPORTED = "reported"          # verbatim from a filing/XBRL fact
    DERIVED = "derived"            # computed by this engine from other quantities/results
    ASSUMPTION = "assumption"      # analyst/default input; MUST be explicit (closes G2)
    # P1: USER_SUPPLIED, FORECAST — to complete Constitution II's four-way distinction.


@dataclass(frozen=True)
class Quantity:
    """A single decimal value with exactly-one-lineage provenance, unit, period, and stamp."""
    value: Decimal
    unit: Unit
    period: FiscalPeriod               # what the value measures (closes G10)
    provenance: Provenance
    as_of: datetime                    # public-availability (REPORTED/ASSUMPTION); tz-aware. For
                                       # DERIVED this is advisory only — availability is resolved
                                       # from parents at compute time, not trusted here (G5)
    source_span_id: str | None = None      # required iff REPORTED
    assumption_id: str | None = None       # required iff ASSUMPTION
    derived_from: tuple[str, ...] = ()     # required iff DERIVED: parent result_ids/span_ids

    def __post_init__(self) -> None:
        _require_decimal(self.value, "Quantity.value")
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        # "iff" enforced BOTH ways: a stray extra lineage field would otherwise be silently
        # preferred by an or-chain downstream, putting the wrong id into the content address.
        has = (bool(self.source_span_id), bool(self.assumption_id), bool(self.derived_from))
        expected = {
            Provenance.REPORTED: (True, False, False),
            Provenance.ASSUMPTION: (False, True, False),
            Provenance.DERIVED: (False, False, True),
        }[self.provenance]
        if has != expected:
            raise ValueError(
                f"{self.provenance.value} quantity must carry exactly its own lineage field"
            )
        for lid in filter(None, (self.source_span_id, self.assumption_id, *self.derived_from)):
            _require_safe_id(lid, "lineage id")

    def lineage_tag(self) -> str:
        """Selected BY KIND, never by or-chain."""
        if self.provenance is Provenance.REPORTED:
            assert self.source_span_id is not None
            return self.source_span_id
        if self.provenance is Provenance.ASSUMPTION:
            assert self.assumption_id is not None
            return self.assumption_id
        return ";".join(self.derived_from)   # components slug-validated: ";" cannot be forged

    def lineage_key(self) -> str:
        """Stable, injective identity fragment for content-addressing."""
        return (f"{self.provenance.value}:{self.unit.key()}:{self.period.key()}:"
                f"{_canon_decimal(self.value)}:{_utc_key(self.as_of)}:{self.lineage_tag()}")


@dataclass(frozen=True)
class Range:
    """Sensitivity band → waterfall / tornado / sensitivity-heatmap viz (spec §8.5)."""
    low: Decimal
    mid: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        for f in ("low", "mid", "high"):
            _require_decimal(getattr(self, f), f"Range.{f}")
        if not (self.low <= self.mid <= self.high):
            raise ValueError(f"band not monotonic: {self.low} <= {self.mid} <= {self.high}")


@dataclass(frozen=True)
class AssumptionSet:
    """A named, immutable scenario overlay: bull/base/bear = three AssumptionSets over ONE
    graph. Scenario diffing is mechanical (same graph, two sets, subtract per node). See §5."""
    assumption_set_id: str
    label: str                                 # "base", "bull", "bear", ...
    values: tuple[tuple[str, Quantity], ...]   # sorted by assumption_id, unique

    def __post_init__(self) -> None:
        _require_safe_id(self.assumption_set_id, "assumption_set_id")
        keys = [k for k, _ in self.values]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise ValueError("assumption set entries must be sorted by id and unique")
        for key, q in self.values:
            if q.provenance is not Provenance.ASSUMPTION or q.assumption_id != key:
                raise ValueError(f"entry {key!r} must be an ASSUMPTION keyed by its own id")


@dataclass(frozen=True)
class CalcResult:
    result_id: str                     # UUIDv5(formula_version | canonical pinned inputs) (G7)
    metric: str
    formula_version: str               # e.g. "revenue-driver-v1" (closes G4)
    value: Decimal
    unit: Unit
    period: FiscalPeriod               # derived output period (closes G10)
    band: Range
    input_span_ids: tuple[str, ...]        # REPORTED lineage (deduplicated, sorted)
    assumption_ids: tuple[str, ...]        # ASSUMPTION lineage
    derived_from: tuple[str, ...]          # DERIVED lineage — no input can vanish (closes G3)
    computed_at_cutoff: datetime

    def __post_init__(self) -> None:
        _require_decimal(self.value, "CalcResult.value")
        if self.value != self.band.mid:
            raise ValueError("CalcResult.value must equal band.mid")
```

```python
# packages/calculation-engine/fel_calculation_engine/ids.py  (PROPOSED — not committed as source)
from __future__ import annotations

import uuid
from datetime import datetime

from .models import Quantity, _require_safe_id, _utc_key

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://financial-evidence-lab.dev/calculation-engine")


def result_id(formula_version: str, inputs: dict[str, Quantity], cutoff: datetime) -> str:
    """Content address over EVERY output-affecting input.

    Illustrative join (Option A): injective only while every joined component is SAFE_ID-
    validated and Unit None uses an out-of-alphabet marker. A real M4 port MUST NOT ship
    this join as the production identity — it MUST hash typed canonical JSON of the pinned
    inputs (sorted keys; Decimal/_utc_key canonicalization; JSON null for absent unit axes;
    enums for per_period/measure) and MUST carry adversarial collision tests (delimiter
    forgery, None-vs-sentinel, Decimal rescaling, tz-equivalent as_of).
    """
    _require_safe_id(formula_version, "formula_version")
    for name in inputs:
        _require_safe_id(name, "input name")
    pinned = "|".join(f"{name}={q.lineage_key()}" for name, q in sorted(inputs.items()))
    return str(uuid.uuid5(ID_NAMESPACE, f"{formula_version}|{_utc_key(cutoff)}|{pinned}"))
```

```python
# packages/calculation-engine/fel_calculation_engine/engine.py  (PROPOSED — not committed as source)
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Callable

from .ids import result_id
from .models import (
    MONEY_SCALE, RATIO, CalcResult, Provenance, Quantity, Range,
)

# For DERIVED inputs the caller-claimed as_of is NOT trusted — an elaboration of Constitution
# Principle I (no look-ahead), not a verbatim clause: availability
# must be resolved from the immutable parents. The leaf API takes an injected resolver that
# maps a DERIVED quantity to its parents' effective availability under the run's tenant/
# corpus pin; the §5 graph evaluator supplies this from in-graph parents by construction.
ResolveAvailability = Callable[[Quantity], datetime]


def _require_available(
    q: Quantity, cutoff: datetime, name: str, resolve: ResolveAvailability | None
) -> None:
    if q.provenance is Provenance.DERIVED:
        if resolve is None:   # fail closed: a derived input's own as_of proves nothing
            raise ValueError(
                f"derived input {name!r} needs a parent resolver; caller as_of is untrusted")
        available_at = resolve(q)                        # max over resolved parents
    else:
        available_at = q.as_of                           # REPORTED/ASSUMPTION carry their own
    if available_at > cutoff:                             # no look-ahead
        raise ValueError(f"input {name!r} available {available_at} is after cutoff {cutoff}")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_SCALE, rounding=ROUND_HALF_EVEN)   # deterministic scale


def revenue_next_quarter(
    *,
    prior_revenue: Quantity,      # REPORTED, quarterly currency flow
    qoq_growth: Quantity,         # ASSUMPTION or DERIVED, ratio, measured over the base quarter
    growth_sensitivity: Quantity,  # ASSUMPTION, ratio, value >= 0 — the ± band half-width
    cutoff: datetime,
    resolve_availability: ResolveAvailability | None = None,  # required iff a DERIVED input
    formula_version: str = "revenue-driver-v1",
) -> CalcResult:
    """In-scope M4 driver: next-quarter revenue = prior * (1 + qoq_growth).

    Pure, decimal, deterministic, fail-closed. All financial math lives here, never in a
    prompt. `inputs` is the single source of truth for temporal check, lineage, AND the
    result id — "checked", "pinned", and "traced" are the same set by construction. A DERIVED
    input's availability is resolved from its parents, never taken from its claimed as_of.
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")

    inputs = {
        "prior_revenue": prior_revenue,
        "qoq_growth": qoq_growth,
        "growth_sensitivity": growth_sensitivity,
    }
    for name, q in inputs.items():
        _require_available(q, cutoff, name, resolve_availability)

    # Typed-unit + provenance + period-consistency enforcement (Constitution II). The unit
    # check is structural AND semantic: per_period must be "quarter", or the derived "next
    # quarter" output period would contradict an annual input (the G10 metric-name trap).
    if qoq_growth.unit != RATIO or growth_sensitivity.unit != RATIO:
        raise ValueError("qoq_growth and growth_sensitivity must be ratio-measure units")
    if prior_revenue.unit.currency is None or prior_revenue.unit.per_period != "quarter":
        raise ValueError("prior_revenue must be a quarterly currency flow")
    if growth_sensitivity.provenance is not Provenance.ASSUMPTION:
        raise ValueError("growth_sensitivity must be an explicit assumption")
    if qoq_growth.provenance not in (Provenance.ASSUMPTION, Provenance.DERIVED):
        raise ValueError("qoq_growth must be an assumption or a derived quantity")
    if qoq_growth.period != prior_revenue.period:
        raise ValueError("qoq_growth must be measured over the base quarter")
    if prior_revenue.value <= 0:
        raise ValueError("prior_revenue must be positive")
    if growth_sensitivity.value < 0:
        raise ValueError("growth_sensitivity must be >= 0")

    one = Decimal(1)
    mid = prior_revenue.value * (one + qoq_growth.value)
    low = prior_revenue.value * (one + qoq_growth.value - growth_sensitivity.value)
    high = prior_revenue.value * (one + qoq_growth.value + growth_sensitivity.value)
    if low < 0:   # negative projected revenue signals a broken assumption — reject, don't clamp
        raise ValueError("low band is negative revenue; sensitivity/growth assumption invalid")

    def ids_of(kind: Provenance) -> tuple[str, ...]:
        out: list[str] = []
        for q in inputs.values():
            if q.provenance is kind:
                out.extend(q.derived_from if kind is Provenance.DERIVED else [q.lineage_tag()])
        return tuple(sorted(dict.fromkeys(out)))   # deduplicated, deterministic order

    return CalcResult(
        result_id=result_id(formula_version, inputs, cutoff),
        metric="revenue_next_q",
        formula_version=formula_version,
        value=_money(mid),
        unit=prior_revenue.unit,                          # propagate, don't hard-code
        period=prior_revenue.period.next_quarter(),       # derived output period (closes G10)
        band=Range(low=_money(low), mid=_money(mid), high=_money(high)),
        input_span_ids=ids_of(Provenance.REPORTED),
        assumption_ids=ids_of(Provenance.ASSUMPTION),
        derived_from=ids_of(Provenance.DERIVED),
        computed_at_cutoff=cutoff,
    )
```

**Derived-lineage cutoff resolution (rev 4 note; sketch hardened in rev 5).** The leaf API
no longer trusts a `DERIVED` input's claimed `as_of`: `_require_available` requires an
injected `resolve_availability` callback and fails closed without one. A real port must
still resolve `derived_from` to immutable parent `CalcResult`/source artifacts under the
run's tenant and corpus pin, derive availability as the maximum over those parents, and
reject a derived input whose claimed `as_of` disagrees with the resolved value. The §5
graph evaluator makes this natural — derived quantities are produced *by* the evaluator
from in-graph parents, never accepted from outside it.

**Identity encoding (rev 6 decision).** Sketch joins use Option A (SAFE_ID tokens + NUL for
absent `Unit` axes) because `SAFE_ID` must keep `"-"` for UUID lineage ids — banning the
hyphen would break `source_span_id` / `assumption_id` validation. Production `result_id`
(Option C) MUST hash typed canonical JSON instead of joining strings; the illustrative
`ids.py` fence is not the M4 contract. (Option B — length-prefixed TLV encoding of each
component, where every field is written as its byte length followed by its bytes — also
removes delimiter-forgery risk, but it is hand-rolled and less legible than JSON, so Option C
is preferred over it.)

## 5. M4 adaptation: a driver-graph evaluator, not a function library

The MVP's centerpiece surface is the **Revenue Model Composer** (spec §8.5) — "a node-based
causal graph backed by a deterministic calculation engine", rendered with React Flow (locked
via spec §10.1 and the constitution's approved-libraries constraint). A flat library of
`revenue_next_quarter()`-style functions does not compose into that. The right shape for
`M4-MODEL-CALC`:

- **Formulas are node types.** Each versioned formula (`revenue-driver-v1`, `gross-profit-v1`,
  …) is a node whose parameters bind either to a `Quantity` leaf or to another node's output.
- **`derived_from` already gives the edges.** A node's `CalcResult` feeds downstream nodes as a
  `DERIVED` `Quantity` whose `derived_from = (upstream.result_id,)` — the lineage chain and the
  visual graph are the *same data structure*.
- **Evaluation is one topological pass** under a cutoff and an `AssumptionSet`:
  `evaluate_graph(graph, assumption_set, cutoff) -> dict[node_id, CalcResult]`. Pure and
  deterministic; cycles are rejected fail-closed.
- **Content-addressed ids give free memoization.** An unchanged subgraph under unchanged
  assumptions re-hashes to identical `result_id`s — recomputation is skipped and, more
  importantly, *provably unnecessary* (reproducibility as a cache key). This claim is only as
  strong as the id's injectivity and canonicality — hence the slug validation and UTC
  normalization in §4.
- **Scenarios are `AssumptionSet` overlays.** Bull/base/bear = three named immutable sets over
  one graph. Scenario diffing is mechanical — same graph, two sets, subtract per node — which
  is precisely the data the waterfall / PVM-bridge / tornado visualizations consume. FinRobot
  has nothing like this; it is the piece FEL's spec wants that the donor cannot supply.

## 6. Contracts and eval gates (the actual ADR moment)

- **Contract publication:** the web viz (ECharts/React Flow) needs `CalcResult`, `Range`,
  `Unit`, `FiscalPeriod`, and `AssumptionSet` as JSON Schemas + generated TS client in
  `packages/contracts/` — an additive minor (v0.5.0 after M3's v0.4.0, per `VERSIONING.md`).
  *That* is the moment requiring `ADR-00NN-calc-engine` + a `contract-change` issue, and where
  `Provenance`/`Quantity` must be reconciled with §11.4 `reported_or_derived` and §11.3 states.
- **Eval gates from day one:** golden-file tests with hand-computed decimal expectations
  (house practice — cf. `workers/tests/test_parser_golden.py`); the property tests spec §20.1
  mandates "for units, periods, decimal arithmetic, and model graphs" — Hypothesis is the
  natural tool but is a *proposed* dependency, not yet in the repo; id-stability tests
  (Decimal re-scaling `0.10` ≡ `0.1000`, timezone-offset equivalence, dict ordering); unit /
  period / provenance rejection tests. At M5, rolling-origin backtests score `Range` coverage
  against spec §19.6's release gate: empirical coverage of the nominal 80% interval must land
  in 75–85%.
- **License hygiene:** the port MUST be clean-room — FinRobot is Apache-2.0, FEL is MIT. If
  any FinRobot source or prompt text is copied verbatim during implementation, add Apache-2.0
  attribution + a NOTICE / third-party-licenses entry and confirm MIT/Apache-2.0 compatibility
  before commit.

## 7. Where the "agent-team" fits (M3/M5 orchestration)

FinRobot wraps its engine with 8 section-writer LLM agents (`equity_agents/agent_manager.py`)
that *narrate* the numbers. FEL already has the compliant equivalent frozen in contract:
`StructuredLLMProvider` (ADR-0007, `packages/providers/fel_providers/interfaces.py`):

- **Engine (§4–§5)** produces `CalcResult`s with full lineage. Deterministic. No model.
- **Narration agent** consumes a `CalcResult` and emits prose *citing* `input_span_ids` /
  `derived_from` — via `generate_structured(...)` with a JSON-Schema output, bounded by
  ADR-0007's default caps (10 calls / 100k in / 20k out / USD 2.00 / 600s) and
  **manual-approval-only** review (ADR-0007 decision 7).
- **No agent-to-agent conversation** (ADR-0007 decision 5). The "team" is a fixed pipeline of
  typed roles over the existing Postgres queue — not FinRobot's AutoGen group chat.

## 8. Proposed P1 expansion: valuation, done the FEL way

*Governance caveat first:* this section proposes amending spec §4.2 non-goals, and `specs/`
**is** an AGENTS.md shared path — so adopting it requires an integration-lead-gated spec
amendment + ADR. It is included as a clearly-marked proposal the lead can accept or strike.

The compelling argument for the expansion is that **FEL's existing ingestion closes FinRobot's
worst valuation shortcuts with *sourced* data**:

1. **Net debt becomes a reported fact, not `0.1 × EV`.** FEL already ingests XBRL company
   facts (`workers/src/fel_workers/ingestion/company_facts.py`). Net debt = debt − cash from
   the balance sheet, each component a `REPORTED` quantity with a `source_span_id`. The
   donor's circular haircut (G2) disappears, and its band-anchoring bug (net debt computed
   from mid-EV, then subtracted unchanged from low/high EVs) is fixed by recomputing per
   scenario.
2. **WACC becomes a `DERIVED` sub-graph with real lineage — via FRED.** FEL ingests
   vintage-aware FRED/ALFRED macro series (`workers/src/fel_workers/ingestion/fred.py`).
   Risk-free rate = a sourced FRED observation at the cutoff; equity risk premium and beta =
   explicit `ASSUMPTION`s in the scenario's `AssumptionSet`; WACC = a derived node whose
   `derived_from` points at all of them. FinRobot's `wacc: 0.10` magic number becomes a fully
   traceable sub-graph. **DCF with claim-level provenance on the discount rate is something
   FinRobot structurally cannot do** — the single strongest "FEL does valuation better" story.
3. **DCF is just another driver subgraph** — `fcf → growth phases → terminal value → PV →
   equity value → per-share`, each a node under §5's evaluator, with the G9 guard
   (`wacc > terminal_growth`, including band shifts) as node-level validation. No new engine
   concepts are needed; P1 valuation is *content*, not *architecture*.
4. **The football-field chart** then legitimately enters the P1 spec as "per-method `Range`s
   rendered side by side" — the anti-synthesis presentation §2 argues for.

Donor bugs recorded so a P1 port does not inherit them: circular `net_debt = 0.1·EV` (G2);
unguarded terminal-value divisor `wacc − g` (G9); pandas `.std()` on a single historical
multiple → `NaN` propagated into bands; `_get_metric` strips `%` without dividing by 100
(latent 100× error, G11).

## 9. Recommendation

1. Keep this as a research draft; do not merge code into `packages/calculation-engine`.
2. When `M4-MODEL-CALC` is dispatched, implement under that issue's `allowed_paths`, following
   §5's graph-evaluator shape. First slice: `revenue_next_quarter` + the §6 golden/property
   tests — mirroring the M2 "first slice" discipline.
3. Raise `ADR-00NN-calc-engine` + `contract-change` at the §6 contract-publication moment.
4. Decide §8 (P1 valuation expansion) separately via a spec amendment the integration lead
   gates; if accepted, sequence it after M5 since it reuses the §5 evaluator unchanged.
5. Treat FinRobot as a *functional sketch to be rewritten under FEL invariants*, never a drop-in.

## 10. Review and verification

This draft was hardened across several adversarial and PR-review passes (a three-lens agent
team, two skeleton attacks, and PR #117's independent review streams). The durable design
decisions those passes produced are recorded where they apply rather than narrated here:

- `next_quarter` uses calendar-**month** arithmetic, not day-count cloning, so it does not
  drift ~5 days/year (§4 code).
- `SAFE_ID` slug validation + exactly-one-lineage selection by kind keep the content address
  injective, so §5's memoization cannot return the wrong financial result as a "cache hit"
  (§4).
- The `measure` axis makes a ratio, a count, and an un-normalized percent structurally
  distinct, closing the donor's 100× bug (G11, §3/§4).
- Absent `Unit` axes are encoded with a NUL marker **outside** the `SAFE_ID` alphabet so
  `Unit(None,…)` cannot collide with `Unit("-",…)`; production `result_id` (Option C) must
  hash typed canonical JSON regardless (§4 "Identity encoding").
- A `DERIVED` input's claimed `as_of` is never trusted — availability is resolved from
  immutable parents via an injected resolver that fails closed without one (G5; §4
  "Derived-lineage cutoff resolution").

The §4 blocks are illustrative, not a committed test target: their executable verification
belongs in the M4 package's golden/property tests (§6) and can be reproduced standalone via
§11. This doc makes no standing "all checks pass" claim — the authoritative checks are those
deferred package tests.

## 11. Reproduction

From the repo root, standard library only:

1. Extract the three fenced Python blocks from §4 into `models.py`, `ids.py`, `engine.py`
   in a scratch package directory (doc order = file order), rewriting the relative
   `from .` imports to package-local absolute imports.
2. Drive `revenue_next_quarter` with: a REPORTED quarterly `prior_revenue`
   (`Unit(currency="USD", per_period="quarter")`), an ASSUMPTION or DERIVED `qoq_growth`
   and ASSUMPTION `growth_sensitivity` (both `RATIO`, same `FiscalPeriod` as the base),
   and a tz-aware cutoff after every `as_of`.
3. Expected: exact decimal band (`1,000,000 × 1.05 = 1,050,000.00` to the cent, monotonic);
   `result_id` stable under Decimal re-scaling (`0.05` ≡ `0.0500`) and timezone-offset
   changes, different under any band-affecting input change; derived output period exact
   over 8 successive quarters (incl. year rollover and leap year); every fail-closed guard
   raising its typed error (float/non-finite values, look-ahead `as_of`, missing or extra
   lineage fields, delimiter-bearing ids or unit components, unit/period mismatches,
   negative sensitivity, negative low band, non-monotonic `Range`, unsorted or mis-keyed
   `AssumptionSet`); `Unit(None,None,None).key() != Unit("-","-","-").key()` (None-vs-
   sentinel non-collision under the NUL marker).
