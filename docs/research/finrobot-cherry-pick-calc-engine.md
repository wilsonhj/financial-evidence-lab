# Cherry-pick study: FinRobot valuation engine → FEL calculation-engine

**Status:** Proposal / research draft (NOT an accepted ADR)
**Date:** 2026-07-19
**Author:** multi-agent analysis session (`claude/finrobot-multi-agent-analysis-fd6byx`)
**Scope guard:** Illustrative code only — no source is added under `packages/calculation-engine/**`.
`packages/calculation-engine/**` is the `M4-MODEL-CALC` package's `allowed_path`
(`docs/handoff/workstreams.yaml`; owner `T0403`), **not** an AGENTS.md shared path.
So the engine's *internal* source lands as normal work under the M4 issue. An accepted
ADR + `contract-change` label is required only when its public types are published into
`packages/contracts/`, or a migration is added under `db/migrations/` — i.e. when a
**shared path** is touched, not on the first internal commit. This study lives in
`docs/research/` (not a shared path) precisely so it needs neither.

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

## 2. Scope reality check (important)

FEL's MVP (`specs/001-financial-evidence-lab/spec.md` §3, non-goal §4.2) is **revenue and
gross-profit driver modeling only** — no three-statement model, no DCF, no valuation, no price
targets. So FinRobot's DCF/EV-EBITDA *math is out of MVP scope*. What transfers is the **engine
pattern**, not the valuation formulas:

| Transferable at M4 | Deferred to P1 |
|---|---|
| Deterministic calc primitive with typed inputs/outputs | DCF / WACC / terminal value |
| Every input carries source-span lineage + provenance kind | EV/EBITDA & peer-multiple valuation |
| `{low, mid, high}` range → waterfall / tornado / sensitivity-heatmap viz (spec §8) | Confidence-weighted multi-method synthesis |
| Versioned formula id + deterministic, content-addressed result id | "Football field" valuation chart (a FinRobot chart; **not** in FEL spec §8) |

The skeleton in §4 therefore demonstrates the pattern on an **in-scope revenue driver**, with
valuation shown only as a commented P1 extension point.

## 3. Compliance gaps — FinRobot shortcuts vs. FEL invariants

The real value of the study: what "FEL-compliant" costs relative to the donor.

| # | FinRobot code | FEL invariant violated | Required fix |
|---|---|---|---|
| G1 | `float` throughout (`target_price: float`, `ebitda * multiple`) | Constitution II: decimal arithmetic; spec §11.4 "no binary float for money" | `Decimal` end-to-end, constructed from strings; runtime type guard |
| G2 | `net_debt = ev * 0.1`, `fcf = ebitda * 0.6` — silent magic numbers (and `net_debt = 0.1·EV` is *definitionally circular*: EV ≡ equity + net debt, so this is just a flat 10% haircut) | Provenance: reported/derived/assumption/forecast must stay distinguishable (Constitution II; spec §11.4) | Every non-sourced number is an explicit typed `Assumption` with an id, temporal stamp, and unit — never inline |
| G3 | Inputs are bare dict lookups (`financial_data.get('ebitda', 0)`) | Lineage chain `source → span → fact → assumption → formula → forecast` (spec §11.4, §11.3) | Each input carries `source_span_id` (REPORTED), `assumption_id` (ASSUMPTION), or `derived_from` (DERIVED) |
| G4 | `confidence=0.7` hard-coded, then used as blend weight in `synthesize_valuation` | Deterministic, versioned formulas | Confidence only from a versioned calibrator (`isotonic-v1`, cf. ADR-0007) or dropped; no magic constants |
| G5 | No temporal stamping; reads "latest" column blindly | Constitution I: a calc at cutoff T sees only evidence public ≤ T (backtests too) | Every input carries `as_of`; engine refuses any input newer than the run cutoff |
| G6 | `except:` swallow-all returning `0` | Test-first / fail-closed | Typed errors; a missing required input raises, never silently `0` |
| G7 | No result identity | Deterministic content-addressed IDs (cf. `packages/retrieval/fel_retrieval/ids.py`) | `result_id = UUIDv5(formula_version | canonical(pinned inputs))` covering *every* output-affecting input |
| G8 | Mutable `self.valuation_results` accumulator | Immutable, reproducible artifacts | Pure functions returning frozen dataclasses |
| G9 | Terminal value `fcf·(1+g)/(wacc−g)` with no guard | Fail-closed math | P1 DCF must reject `wacc ≤ terminal_growth` (incl. the ±1% band shifts) before dividing |

## 4. FEL-compliant port skeleton (illustrative — hardened after code review)

House style mirrored from `packages/retrieval/fel_retrieval/` and
`packages/providers/fel_providers/interfaces.py`. Import package name follows the `fel_<dir>`
norm: dir `calculation-engine` → package `fel_calculation_engine`. UUIDv5 id logic lives in a
dedicated `ids.py` (mirroring `fel_retrieval/ids.py`), not inline in the engine.

```python
# packages/calculation-engine/fel_calculation_engine/models.py  (PROPOSED — not committed as source)
"""Typed inputs/outputs for the deterministic calculation engine.

Constitution II: authoritative math is decimal, typed-unit, versioned, deterministic. No LLM.
Every quantity is sourced (source_span_id), an explicit assumption (assumption_id), or a
derived value that carries its upstream lineage (derived_from). NOTE for a real port: this
`Provenance` sketch must be reconciled with the frozen data model before adoption — spec §11.4
`NormalizedFinancialFact.reported_or_derived` (a binary flag + source_span_id) and the §11.3
closed claim-state set — and with Constitution II's four-way reported/derived/user-supplied/
forecast distinction. It is shown here only to make lineage obligations concrete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

# Money rounding policy (applied by the engine): cents at ROUND_HALF_EVEN (banker's, unbiased).
MONEY_SCALE = Decimal("0.01")
RATIO_SCALE = Decimal("0.000001")


def _require_decimal(value: object, field: str) -> Decimal:
    # Reject float outright (Constitution II). Upstream must build Decimals from strings
    # (XBRL/market values are decimal strings — cf. MarketBar in fel_providers/interfaces.py).
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal, got {type(value).__name__}")
    return value


class Provenance(str, Enum):
    REPORTED = "reported"          # verbatim from a filing/XBRL fact
    DERIVED = "derived"            # computed by this engine from other quantities/results
    ASSUMPTION = "assumption"      # analyst/default input; MUST be explicit (closes G2)
    # P1: USER_SUPPLIED, FORECAST — to complete Constitution II's four-way distinction.


@dataclass(frozen=True)
class Quantity:
    """A single decimal value with mandatory provenance + lineage + temporal stamp."""
    value: Decimal
    unit: str                          # "USD/quarter", "ratio", "count", ...
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
        return f"{self.provenance.value}:{self.unit}:{canon}:{self.as_of.isoformat()}:{tag}"


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
class CalcResult:
    result_id: str                     # UUIDv5(formula_version | canonical pinned inputs) (G7)
    metric: str
    formula_version: str               # e.g. "revenue-driver-v1" (closes G4)
    value: Decimal
    unit: str
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
from .models import CalcResult, MONEY_SCALE, Provenance, Quantity, Range


def _require_available(q: Quantity, cutoff: datetime, name: str) -> None:
    if q.as_of > cutoff:                       # no look-ahead (closes G5)
        raise ValueError(f"input {name!r} as_of {q.as_of} is after cutoff {cutoff}")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_SCALE, rounding=ROUND_HALF_EVEN)   # deterministic scale (S3)


def revenue_next_quarter(
    *,
    prior_revenue: Quantity,      # REPORTED, currency-flow unit
    qoq_growth: Quantity,         # ASSUMPTION or DERIVED, unit "ratio"
    growth_sensitivity: Quantity,  # ASSUMPTION, unit "ratio", value >= 0 — the ± band half-width
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

    # Typed-unit enforcement (Constitution II): reject dimensionally invalid inputs.
    if qoq_growth.unit != "ratio" or growth_sensitivity.unit != "ratio":
        raise ValueError("qoq_growth and growth_sensitivity must be dimensionless ratios")
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

    def ids(kind: Provenance) -> tuple[str, ...]:
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
        unit=prior_revenue.unit,                    # propagate, don't hard-code (S4)
        band=Range(low=_money(low), mid=_money(mid), high=_money(high)),
        input_span_ids=ids(Provenance.REPORTED),
        assumption_ids=ids(Provenance.ASSUMPTION),
        derived_from=ids(Provenance.DERIVED),
        computed_at_cutoff=cutoff,
    )

# P1 EXTENSION (out of MVP scope): dcf_valuation(...), ev_ebitda(...), peer_comps(...) follow
# the same discipline. FinRobot's `net_debt = ev * 0.1` becomes an explicit
# Quantity(provenance=ASSUMPTION, assumption_id="net_debt_pct_of_ev@v1", unit="ratio"), and the
# terminal-value divisor must assert wacc > terminal_growth (incl. ±band shifts) before dividing.
```

## 5. Where the "agent-team" fits (M3/M5 orchestration)

FinRobot wraps its engine with 8 section-writer LLM agents (`equity_agents/agent_manager.py`)
that *narrate* the numbers. FEL already has the compliant equivalent frozen in contract:
`StructuredLLMProvider` (ADR-0007, `packages/providers/fel_providers/interfaces.py`):

- **Engine (§4)** produces `CalcResult` with full lineage. Deterministic. No model.
- **Narration agent** consumes a `CalcResult` and emits prose *citing* `input_span_ids` /
  `derived_from` — via `StructuredLLMProvider.generate_structured(...)` with a JSON-Schema
  output, bounded by ADR-0007 caps (10 calls / 100k in / 20k out / USD 2.00 / 600s) and
  **manual-approval-only** review (ADR-0007 §7).
- **No agent-to-agent conversation** (ADR-0007 §5). The "team" is a fixed pipeline of typed
  roles over the existing Postgres queue — not FinRobot's AutoGen group chat.

Adopt FinRobot's *narration-over-deterministic-core* shape; reject its autonomous-agent
orchestration, which FEL's constitution already rules out.

## 6. Recommendation

1. Keep this as a research draft; do not merge code into `packages/calculation-engine`.
2. When `M4-MODEL-CALC` is dispatched, implement the engine's internal source under that issue's
   `allowed_paths`. Raise a formal `ADR-00NN-calc-engine` + `contract-change` issue only at the
   point the engine's public types are published into `packages/contracts/` (or a migration is
   added) — reconciling `Provenance`/`Quantity` with §11.4 `reported_or_derived` and §11.3 states.
3. First real slice: a single driver (`revenue_next_quarter`) with property tests for decimal
   exactness, band monotonicity, and temporal-cutoff refusal — mirroring the M2 "first slice".
4. Treat FinRobot as a *functional sketch to be rewritten under FEL invariants*, never a drop-in.

## 7. Multi-agent code review — findings incorporated

This draft was reviewed by a three-lens agent team (FEL-invariant compliance, financial-math
correctness, house-style/governance). Their blockers were folded into §3–§4 above:

- **DERIVED lineage hole (blocker):** the original enum added `DERIVED` but never validated it,
  and derived inputs vanished from both lineage tuples and the result id. Fixed: `__post_init__`
  now requires `derived_from`, and `CalcResult` carries a `derived_from` tuple.
- **`growth_sensitivity` magic number (blocker):** originally a bare `Decimal` outside `inputs` —
  reintroducing the exact G2 shortcut. Fixed: promoted to a sourced `Quantity`, folded into
  `inputs`, so it is temporal-checked, traced, and pinned into the id.
- **Non-canonical Decimal in id (major):** `str(Decimal)` made `0.10` ≠ `0.1000`. Fixed via
  `lineage_key()` using `format(value.normalize(), "f")` plus unit + `as_of`.
- **No money rounding policy (major):** added `MONEY_SCALE` + `ROUND_HALF_EVEN` quantization.
- **Unenforced units / `Range` monotonicity / negative revenue (major/medium):** added unit
  checks, `Range.__post_init__` ordering, and a negative-band rejection.
- **Governance overreach (medium):** corrected — `packages/calculation-engine/**` is M4's
  `allowed_path`, not a shared path; ADR/contract-change attaches at `packages/contracts/`.
- **Package name / id module / §8 football-field / provenance taxonomy (medium/low):** renamed
  to `fel_calculation_engine`, split `ids.py`, removed the incorrect §8 football-field claim, and
  added the §11.3/§11.4 reconciliation note.
- **Donor bugs confirmed (context):** `net_debt = 0.1·EV` is definitionally circular (G2);
  unguarded terminal-value divisor `wacc − g` (G9); `.std()` on one historical multiple → `NaN`;
  `_get_metric` strips `%` without ÷100. Recorded so a P1 port does not inherit them.
