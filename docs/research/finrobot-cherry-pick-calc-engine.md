# Cherry-pick study: FinRobot valuation engine → FEL calculation-engine

**Status:** Proposal / research draft (NOT an accepted ADR)
**Date:** 2026-07-19 (rev 2 — post-review + M4 design sketch + proposed P1 roadmap)
**Author:** multi-agent analysis session (`claude/finrobot-multi-agent-analysis-fd6byx`)
**Scope guard:** Illustrative code only — no source is added under `packages/calculation-engine/**`.
`packages/calculation-engine/**` is the `M4-MODEL-CALC` package's `allowed_path`
(`docs/handoff/workstreams.yaml`; owner `T0403`), **not** an AGENTS.md shared path.
So the engine's *internal* source lands as normal work under the M4 issue. An accepted
ADR + `contract-change` label is required only when a **shared path** is touched: publishing
the engine's public types into `packages/contracts/`, adding a migration under
`db/migrations/`, or — for §8 of this doc — amending `specs/001-financial-evidence-lab/`
(the `specs/` tree is a shared path). This study lives in `docs/research/` (not a shared
path) precisely so it needs neither.

## 1. What was studied

Source: `AI4Finance-Foundation/FinRobot`,
`finrobot_equity/core/src/modules/valuation_engine.py` (420 lines) — a pure-Python, LLM-free
`ValuationEngine` computing EV/EBITDA, peer-comparison, and simplified DCF valuations, then
exposing `generate_football_field_data()` (per-method `{low, mid, high}` ranges),
`synthesize_valuation()` (confidence-weighted blend), and `explain_valuation_differences()`.

Its principle — **"deterministic numbers in code, LLM only narrates"** — is exactly FEL
Constitution **Principle II** (*"Language models MAY propose or explain assumptions but MUST
NOT execute authoritative financial math… Authoritative monetary calculations MUST use decimal
arithmetic, typed units, explicit fiscal periods, and deterministic formulas."*). That
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
| `{low, mid, high}` range → waterfall / tornado / sensitivity-heatmap viz (spec §8) | "Football field" chart (per-method ranges side by side) | |
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
| G1 | `float` throughout (`target_price: float`, `ebitda * multiple`) | Constitution II: decimal arithmetic; spec §11.4 "no binary float for money" | `Decimal` end-to-end, constructed from strings; runtime type guard |
| G2 | `net_debt = ev * 0.1`, `fcf = ebitda * 0.6` — silent magic numbers (and `net_debt = 0.1·EV` is *definitionally circular*: EV ≡ equity + net debt, so this is just a flat 10% haircut) | Provenance: reported/derived/assumption/forecast must stay distinguishable (Constitution II; spec §11.4) | Every non-sourced number is an explicit typed `Assumption` with an id, temporal stamp, and unit — never inline |
| G3 | Inputs are bare dict lookups (`financial_data.get('ebitda', 0)`) | Lineage chain `source → span → fact → assumption → formula → forecast` (spec §11.4, §11.3) | Each input carries `source_span_id` (REPORTED), `assumption_id` (ASSUMPTION), or `derived_from` (DERIVED) |
| G4 | `confidence=0.7` hard-coded, then used as blend weight in `synthesize_valuation` | Deterministic, versioned formulas | Rejected outright (§2); calibrated confidence only via `isotonic-v1` (ADR-0007) |
| G5 | No temporal stamping; reads "latest" column blindly | Constitution I: a calc at cutoff T sees only evidence public ≤ T (backtests too) | Every input carries `as_of`; engine refuses any input newer than the run cutoff |
| G6 | `except:` swallow-all returning `0` | Test-first / fail-closed | Typed errors; a missing required input raises, never silently `0` |
| G7 | No result identity | Deterministic content-addressed IDs (cf. `packages/retrieval/fel_retrieval/ids.py`) | `result_id = UUIDv5(formula_version | canonical(pinned inputs))` covering *every* output-affecting input |
| G8 | Mutable `self.valuation_results` accumulator | Immutable, reproducible artifacts | Pure functions returning frozen dataclasses |
| G9 | Terminal value `fcf·(1+g)/(wacc−g)` with no guard | Fail-closed math | P1 DCF must reject `wacc ≤ terminal_growth` (incl. the ±1% band shifts) before dividing |
| G10 | No fiscal-period typing — values are addressed by spreadsheet-style year columns (`'2024A'`, `'2025E'`) | Constitution II: **explicit fiscal periods**; publication time (`as_of`) and measured period are different timelines | Every quantity carries a `FiscalPeriod(start, end)`; formulas derive output periods, never leave them implicit in a metric name |

## 4. FEL-compliant port skeleton (illustrative — rev 2, hardened after review)

House style mirrored from `packages/retrieval/fel_retrieval/` and
`packages/providers/fel_providers/interfaces.py`. Import package name follows the `fel_<dir>`
norm: dir `calculation-engine` → package `fel_calculation_engine`. UUIDv5 id logic lives in a
dedicated `ids.py` (mirroring `fel_retrieval/ids.py`), not inline in the engine.

Rev 2 changes vs. rev 1: structured `Unit` type replaces the free string; `FiscalPeriod` added
to `Quantity` and `CalcResult` (closes G10, which the rev-1 skeleton itself violated); output
period is derived, not implied.

```python
# packages/calculation-engine/fel_calculation_engine/models.py  (PROPOSED — not committed as source)
"""Typed inputs/outputs for the deterministic calculation engine.

Constitution II: authoritative math is decimal, typed-unit, explicit-fiscal-period, versioned,
deterministic. No LLM. Every quantity is sourced (source_span_id), an explicit assumption
(assumption_id), or a derived value carrying upstream lineage (derived_from). NOTE for a real
port: this `Provenance` sketch must be reconciled with the frozen data model before adoption —
spec §11.4 `NormalizedFinancialFact.reported_or_derived` (binary flag + source_span_id) and the
§11.3 closed claim-state set — and with Constitution II's four-way reported/derived/
user-supplied/forecast distinction. Shown here only to make lineage obligations concrete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

# Money rounding policy (applied by the engine): cents at ROUND_HALF_EVEN (banker's, unbiased).
MONEY_SCALE = Decimal("0.01")


def _require_decimal(value: object, field: str) -> Decimal:
    # Reject float outright (Constitution II). Upstream must build Decimals from strings
    # (XBRL/market values are decimal strings — cf. MarketBar in fel_providers/interfaces.py).
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class Unit:
    """Structured unit: currency + periodicity. Replaces free-form strings so dimensional
    checks are structural, not string comparisons ('USD/qtr' vs 'USD/quarter')."""
    currency: str | None = None      # ISO 4217 ("USD") or None for dimensionless/counts
    per_period: str | None = None    # "quarter", "year", or None for stocks/ratios

    def key(self) -> str:
        return f"{self.currency or '-'}/{self.per_period or '-'}"


DIMENSIONLESS = Unit()


@dataclass(frozen=True)
class FiscalPeriod:
    """The span a value MEASURES — distinct from `as_of` (when it became public). Closes G10."""
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("fiscal period start after end")

    def next_quarter(self) -> FiscalPeriod:
        # Illustrative: real port uses the issuer's fiscal calendar from ingested facts,
        # not naive month arithmetic (4-4-5 calendars, 53-week years).
        days = (self.end - self.start).days
        from datetime import timedelta
        start = self.end + timedelta(days=1)
        return FiscalPeriod(start=start, end=start + timedelta(days=days))

    def key(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


class Provenance(str, Enum):
    REPORTED = "reported"          # verbatim from a filing/XBRL fact
    DERIVED = "derived"            # computed by this engine from other quantities/results
    ASSUMPTION = "assumption"      # analyst/default input; MUST be explicit (closes G2)
    # P1: USER_SUPPLIED, FORECAST — to complete Constitution II's four-way distinction.


@dataclass(frozen=True)
class Quantity:
    """A single decimal value with mandatory provenance, lineage, unit, period, and stamp."""
    value: Decimal
    unit: Unit
    period: FiscalPeriod               # what the value measures (closes G10)
    provenance: Provenance
    as_of: datetime                    # public-availability timestamp; tz-aware UTC (closes G5)
    source_span_id: str | None = None      # required iff REPORTED (closes G3)
    assumption_id: str | None = None       # required iff ASSUMPTION (closes G2/G4)
    derived_from: tuple[str, ...] = ()     # required iff DERIVED: parent result_ids/span_ids

    def __post_init__(self) -> None:
        _require_decimal(self.value, "Quantity.value")
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware (UTC)")
        # Exhaustive, fail-closed per-kind lineage check (closes the DERIVED hole).
        if self.provenance is Provenance.REPORTED and not self.source_span_id:
            raise ValueError("reported quantity requires source_span_id")
        if self.provenance is Provenance.ASSUMPTION and not self.assumption_id:
            raise ValueError("assumption quantity requires assumption_id")
        if self.provenance is Provenance.DERIVED and not self.derived_from:
            raise ValueError("derived quantity requires non-empty derived_from")

    def lineage_key(self) -> str:
        """Stable identity fragment for content-addressing (never None)."""
        tag = self.source_span_id or self.assumption_id or ";".join(self.derived_from)
        # Canonicalize the Decimal so 0.10 / 0.1000 / 1E-1 hash identically.
        canon = format(self.value.normalize(), "f")
        return (f"{self.provenance.value}:{self.unit.key()}:{self.period.key()}:"
                f"{canon}:{self.as_of.isoformat()}:{tag}")


@dataclass(frozen=True)
class Range:
    """Sensitivity band → waterfall / tornado / sensitivity-heatmap viz (spec §8)."""
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
    graph. Scenario diffing is mechanical (same graph, two sets, subtract per node) — exactly
    the data a waterfall/PVM bridge needs. See §5."""
    assumption_set_id: str
    label: str                                   # "base", "bull", "bear", ...
    values: tuple[tuple[str, "Quantity"], ...]   # (assumption_id → Quantity), sorted, immutable


@dataclass(frozen=True)
class CalcResult:
    result_id: str                     # UUIDv5(formula_version | canonical pinned inputs) (G7)
    metric: str
    formula_version: str               # e.g. "revenue-driver-v1" (closes G4)
    value: Decimal
    unit: Unit
    period: FiscalPeriod               # derived output period (closes G10)
    band: Range
    input_span_ids: tuple[str, ...]        # REPORTED lineage
    assumption_ids: tuple[str, ...]        # ASSUMPTION lineage
    derived_from: tuple[str, ...]          # DERIVED lineage — no input can vanish (closes G3)
    computed_at_cutoff: datetime
```

```python
# packages/calculation-engine/fel_calculation_engine/ids.py  (PROPOSED — not committed as source)
from __future__ import annotations

import uuid

from .models import Quantity

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://financial-evidence-lab.dev/calculation-engine")


def result_id(formula_version: str, inputs: dict[str, Quantity], cutoff: str) -> str:
    """Content address over EVERY output-affecting input (canonicalized, delimiter-safe)."""
    pinned = "|".join(f"{name}={q.lineage_key()}" for name, q in sorted(inputs.items()))
    return str(uuid.uuid5(ID_NAMESPACE, f"{formula_version}|{cutoff}|{pinned}"))
```

```python
# packages/calculation-engine/fel_calculation_engine/engine.py  (PROPOSED — not committed as source)
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from .ids import result_id
from .models import (
    DIMENSIONLESS, CalcResult, MONEY_SCALE, Provenance, Quantity, Range,
)


def _require_available(q: Quantity, cutoff: datetime, name: str) -> None:
    if q.as_of > cutoff:                       # no look-ahead (closes G5)
        raise ValueError(f"input {name!r} as_of {q.as_of} is after cutoff {cutoff}")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_SCALE, rounding=ROUND_HALF_EVEN)   # deterministic scale


def revenue_next_quarter(
    *,
    prior_revenue: Quantity,      # REPORTED, currency-flow unit (currency + per_period set)
    qoq_growth: Quantity,         # ASSUMPTION or DERIVED, dimensionless
    growth_sensitivity: Quantity,  # ASSUMPTION, dimensionless, value >= 0 — the ± band half-width
    cutoff: datetime,
    formula_version: str = "revenue-driver-v1",
) -> CalcResult:
    """In-scope M4 driver: next-quarter revenue = prior * (1 + qoq_growth).

    Pure, decimal, deterministic, fail-closed. All financial math lives here, never in a prompt.
    `inputs` is the single source of truth for temporal check, lineage, AND the result id — so
    "checked", "pinned", and "traced" are the same set by construction.
    """
    inputs = {
        "prior_revenue": prior_revenue,
        "qoq_growth": qoq_growth,
        "growth_sensitivity": growth_sensitivity,   # folded in (closes G2/G4/G5/G7 for the band)
    }
    for name, q in inputs.items():
        _require_available(q, cutoff, name)

    # Typed-unit enforcement (Constitution II) — structural, not string comparison.
    if qoq_growth.unit != DIMENSIONLESS or growth_sensitivity.unit != DIMENSIONLESS:
        raise ValueError("qoq_growth and growth_sensitivity must be dimensionless")
    if prior_revenue.unit.currency is None or prior_revenue.unit.per_period is None:
        raise ValueError("prior_revenue must be a currency flow (currency + per_period)")
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
            if q.provenance is not kind:
                continue
            out.extend(q.derived_from if kind is Provenance.DERIVED
                       else [q.source_span_id or q.assumption_id])  # never None by construction
        return tuple(out)

    return CalcResult(
        result_id=result_id(formula_version, inputs, cutoff.isoformat()),
        metric="revenue_next_q",
        formula_version=formula_version,
        value=_money(mid),
        unit=prior_revenue.unit,                          # propagate, don't hard-code
        period=prior_revenue.period.next_quarter(),       # DERIVED output period (closes G10)
        band=Range(low=_money(low), mid=_money(mid), high=_money(high)),
        input_span_ids=ids_of(Provenance.REPORTED),
        assumption_ids=ids_of(Provenance.ASSUMPTION),
        derived_from=ids_of(Provenance.DERIVED),
        computed_at_cutoff=cutoff,
    )
```

## 5. M4 adaptation: a driver-graph evaluator, not a function library

The MVP's centerpiece is the **Revenue Model Composer** — a React Flow *causal driver graph*
(spec §8). A flat library of `revenue_next_quarter()`-style functions does not compose into
that. The right shape for `M4-MODEL-CALC`:

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
  importantly, *provably unnecessary* (reproducibility as a cache key).
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
- **Eval gates from day one** (FEL culture, spec §19.6): golden-file tests with hand-computed
  decimal expectations exact to the cent; property tests (Hypothesis) for band monotonicity,
  temporal-cutoff refusal, and `result_id` stability under Decimal re-scaling
  (`0.10` ≡ `0.1000`) and dict ordering; unit/period rejection tests. At M5, rolling-origin
  backtests score `Range` coverage against the 75–85% interval-coverage gate.

## 7. Where the "agent-team" fits (M3/M5 orchestration)

FinRobot wraps its engine with 8 section-writer LLM agents (`equity_agents/agent_manager.py`)
that *narrate* the numbers. FEL already has the compliant equivalent frozen in contract:
`StructuredLLMProvider` (ADR-0007, `packages/providers/fel_providers/interfaces.py`):

- **Engine (§4–§5)** produces `CalcResult`s with full lineage. Deterministic. No model.
- **Narration agent** consumes a `CalcResult` and emits prose *citing* `input_span_ids` /
  `derived_from` — via `generate_structured(...)` with a JSON-Schema output, bounded by
  ADR-0007 caps (10 calls / 100k in / 20k out / USD 2.00 / 600s) and **manual-approval-only**
  review (ADR-0007 §7).
- **No agent-to-agent conversation** (ADR-0007 §5). The "team" is a fixed pipeline of typed
  roles over the existing Postgres queue — not FinRobot's AutoGen group chat.

## 8. Proposed P1 expansion: valuation, done the FEL way

*Governance caveat first:* this section proposes amending spec §4.2 non-goals, and `specs/`
**is** an AGENTS.md shared path — so adopting it requires an integration-lead-gated spec
amendment + ADR. It is included as a clearly-marked proposal the lead can accept or strike.

The compelling argument for the expansion is that **FEL's existing ingestion closes FinRobot's
worst valuation shortcuts with *sourced* data**:

1. **Net debt becomes a reported fact, not `0.1 × EV`.** FEL already ingests XBRL company
   facts (`workers/src/fel_workers/company_facts.py`). Net debt = debt − cash from the balance
   sheet, each component a `REPORTED` quantity with a `source_span_id`. The donor's circular
   haircut (G2) disappears, and its band-anchoring bug (net debt computed from mid-EV, then
   subtracted unchanged from low/high EVs) is fixed by recomputing per scenario.
2. **WACC becomes a `DERIVED` sub-graph with real lineage — via FRED.** FEL ingests FRED macro
   series (`workers/src/fel_workers/fred.py`). Risk-free rate = a sourced FRED observation at
   the cutoff; equity risk premium and beta = explicit `ASSUMPTION`s in the scenario's
   `AssumptionSet`; WACC = a derived node whose `derived_from` points at all of them.
   FinRobot's `wacc: 0.10` magic number becomes a fully traceable sub-graph. **DCF with
   claim-level provenance on the discount rate is something FinRobot structurally cannot do**
   — this is the single strongest "FEL does valuation better" story.
3. **DCF is just another driver subgraph** — `fcf → growth phases → terminal value → PV →
   equity value → per-share`, each a node under §5's evaluator, with the G9 guard
   (`wacc > terminal_growth`, including band shifts) as node-level validation. No new engine
   concepts are needed; P1 valuation is *content*, not *architecture*.
4. **The football-field chart** then legitimately enters the P1 spec as "per-method `Range`s
   rendered side by side" — the anti-synthesis presentation §2 argues for.

Donor bugs recorded so a P1 port does not inherit them: circular `net_debt = 0.1·EV` (G2);
unguarded terminal-value divisor `wacc − g` (G9); pandas `.std()` on a single historical
multiple → `NaN` propagated into bands; `_get_metric` strips `%` without dividing by 100
(latent 100× error for any rate metric).

## 9. Recommendation

1. Keep this as a research draft; do not merge code into `packages/calculation-engine`.
2. When `M4-MODEL-CALC` is dispatched, implement under that issue's `allowed_paths`, following
   §5's graph-evaluator shape. First slice: `revenue_next_quarter` + the §6 property/golden
   tests — mirroring the M2 "first slice" discipline.
3. Raise `ADR-00NN-calc-engine` + `contract-change` at the §6 contract-publication moment.
4. Decide §8 (P1 valuation expansion) separately via a spec amendment the integration lead
   gates; if accepted, sequence it after M5 since it reuses the §5 evaluator unchanged.
5. Treat FinRobot as a *functional sketch to be rewritten under FEL invariants*, never a drop-in.

## 10. Multi-agent code review — findings incorporated

This draft was reviewed by a three-lens agent team (FEL-invariant compliance, financial-math
correctness, house-style/governance). Blockers folded into §3–§4:

- **DERIVED lineage hole (blocker):** rev 1 added `DERIVED` but never validated it, and derived
  inputs vanished from both lineage tuples and the result id. Fixed: `__post_init__` requires
  `derived_from`, and `CalcResult` carries a `derived_from` tuple.
- **`growth_sensitivity` magic number (blocker):** originally a bare `Decimal` outside `inputs`
  — reintroducing the exact G2 shortcut. Fixed: promoted to a sourced `Quantity`, folded into
  `inputs`, so it is temporal-checked, traced, and pinned into the id.
- **Non-canonical Decimal in id (major):** `str(Decimal)` made `0.10` ≠ `0.1000`. Fixed via
  `lineage_key()` using `format(value.normalize(), "f")` plus unit + period + `as_of`.
- **No money rounding policy (major):** added `MONEY_SCALE` + `ROUND_HALF_EVEN` quantization.
- **Unenforced units / `Range` monotonicity / negative revenue (major/medium):** structural
  `Unit` checks, `Range.__post_init__` ordering, negative-band rejection.
- **Governance overreach (medium):** corrected — `packages/calculation-engine/**` is M4's
  `allowed_path`, not a shared path; ADR/contract-change attaches at `packages/contracts/`
  (and at `specs/` for §8).
- **Package name / id module / §8 football-field / provenance taxonomy (medium/low):** renamed
  to `fel_calculation_engine`, split `ids.py`, football-field re-scoped to P1 (it is not in
  spec §8), §11.3/§11.4 reconciliation note added.

Post-review additions (rev 2, caught after the team pass):

- **G10 fiscal periods:** the rev-1 skeleton itself violated Constitution II's "explicit fiscal
  periods" — `as_of` (publication) and the measured period are different timelines. Added
  `FiscalPeriod` to `Quantity`/`CalcResult`; output periods are derived, with a note that real
  period arithmetic must use the issuer's fiscal calendar (4-4-5, 53-week years), not naive
  month math.
- **Structured `Unit`** replacing free strings; **synthesis re-classified rejected** (§2);
  **§5 graph evaluator + `AssumptionSet`** and **§6 contract/eval plan** added so the doc reads
  as study + M4 design sketch + optional P1 roadmap rather than a donor-repo study alone.
