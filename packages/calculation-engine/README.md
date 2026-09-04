# `@fel/calculation-engine` (`fel_calculation_engine`)

Server-side Decimal calculation engine for the Revenue Model Composer
(spec §8.5, FR-MOD-001 / FR-MOD-002). Authoritative math is Decimal-only,
typed-unit, and deterministic. Language models must not execute it.

## What it does

- Nine node kinds (source fact, assumption, driver, formula, aggregation,
  scenario override, forecast output, validation check, reported output)
- Fail-closed cycle detection and versioned, content-addressed snapshots
- Decimal arithmetic under `CALC_CONTEXT` (34 digits, banker's rounding)
- Closed unit algebra, typed fiscal periods, percent → ratio normalization
- Provenance retained through recalculation; derived cutoffs are `max(parents)`
- Property tests and a deterministic 5,000-node p95 recalculation gate

## Leaf values

Construct Decimals from strings (`Decimal("0.1")`). `Decimal(0.1)` — the
IEEE-754 binary expansion — is rejected at `require_decimal`.

## Tests

```bash
pytest packages/calculation-engine/tests
```

## Module map

| Module | Task | Responsibility |
|---|---|---|
| `units.py`, `periods.py`, `values.py`, `rounding.py`, `nodes.py` | T0401 | Typed units and their closed algebra; `FiscalQuarter`/`FiscalYear` with kind-scoped ordering and `FiscalCalendar` spans; `require_decimal`, `CALC_CONTEXT`, `Quantity`, `Lineage`; ISO 4217 minor units; the nine frozen node kinds |
| `canonical.py`, `graph.py`, `snapshot.py`, `store.py` | T0402 | Typed canonical JSON + sha256 content hashes; `ModelGraph` (edges from `Node.inputs()`, cycle detection, build-time type checks, deterministic order); `GraphSnapshot` (versioned, content-addressed, parent-linked); `SnapshotStore` Protocol + `InMemorySnapshotStore` |
| `engine.py`, `scenario.py`, `telemetry.py` | T0403 | `evaluate()` → immutable `CalcResult`s with full lineage; sparse `Scenario` + `apply_scenario()`; redacted structured events |
| `tests/_gen.py`, `tests/test_properties.py` | T0409 | Seeded deterministic property tests |
| `synthetic.py`, `tests/test_benchmark_recalc.py` | T0410 | Deterministic 5,000-node model and the p95 recalculation gate |

## Graph model

Nine node kinds (spec §8.5), each a frozen dataclass with a slug `node_id`, a
`label` (presentation only — excluded from result identity), a typed `unit`
and a typed `period`:

| Kind | Provenance | Carries | Inputs (edge roles) |
|---|---|---|---|
| `SourceFactNode` | reported | `value`, `as_of`, `source_span_id` (+ optional `fact_id`) | — |
| `AnalystAssumptionNode` | assumption | `value`, `as_of`, `assumption_id` — **no default value exists** | — |
| `OperationalDriverNode` | derived | — | `seed` |
| `FormulaNode` | derived | `operator` (add/sub/mul/div), `formula_version` | `operand[i]` |
| `AggregationNode` | derived | `operator` (`sum` same period / `rollup_year` Q1..Q4 → FY) | `operand[i]` |
| `ScenarioOverrideNode` | assumption | `value`, `as_of`, `scenario_id`, `assumption_id` | `overrides` |
| `ForecastModelOutputNode` | forecast | `value`, `as_of`, `forecast_run_id`, `dataset_cutoff`, `dataset_version` | — |
| `ValidationCheckNode` | derived | `check` (equals/non_negative/less_or_equal/greater_or_equal), `tolerance` | `operand[i]` |
| `ReportedFinancialOutputNode` | derived | `metric_id`, optional `quantum` | `source` |

Edges are derived from `Node.inputs()` — the lineage a node declares and the
graph a UI draws are the same data (`model_edges.role` in spec §11).
`ModelGraph.build()` fails closed on duplicate ids, dangling references
(`MISSING_INPUT`) and cycles (`CYCLE_DETECTED`, carrying a concrete cycle
path), and type-checks every derived node against its inputs before anything
is evaluated: formula unit algebra must reproduce the declared unit, formula
operands must share the output's period *kind*, `sum` operands share the
output period, `rollup_year` operands are exactly the four quarters of the
output year, drivers/outputs match their source's unit and period, and
overrides may only shadow assumptions, drivers or earlier overrides.

The Constitution II four-way split (reported / user-supplied / derived /
forecast) is `Provenance`; `Lineage` enforces exactly one lineage field per
kind (`source_span_id` / `assumption_id` / `derived_from` / `forecast_run_id`)
— never selected by an or-chain.

## Unit algebra

`Unit(kind, currency, per_period)`: kinds `currency` (ISO 4217 code required),
`count`, `percent`, `ratio`; any unit may be a rate `per` a `PeriodKind`. The
algebra is a closed table; every combination not listed raises `UnitError`.

| Operation | Rule |
|---|---|
| `a + b`, `a - b` | units must be identical (including currency and rate denominator) |
| `x * ratio`, `ratio * x` | `x` (ratio is the dimensionless scalar) |
| `currency * count` | `currency` (price × volume) |
| `currency / currency` (same code) | `ratio`; cross-currency raises |
| `currency / count` | `currency` (per-unit amounts) |
| `count / count` | `ratio` |
| `x / ratio` | `x` |
| anything with `percent` in `*` or `/` | raises — normalize with `Quantity.to_ratio()` first (`62.5 %` → `0.625`) |
| rate × rate, rate ÷ rate with different denominators, stock ÷ rate | raise |

Arithmetic runs in `CALC_CONTEXT` (34 significant digits, `ROUND_HALF_EVEN`,
`DivisionByZero`/`InvalidOperation`/`Overflow` trapped → `FORMULA_ERROR`).
Nothing is quantized until a `ReportedFinancialOutputNode`, which quantizes
once to the currency's ISO 4217 minor unit (USD 2, JPY 0, KWD 3; unknown codes
raise) or an explicit `quantum` for non-currency outputs. Rounding therefore
never compounds node-to-node (`test_rounding_happens_once_at_the_reported_edge_and_never_compounds`).

## Periods

`FiscalQuarter(fiscal_year, quarter)` and `FiscalYear(fiscal_year)` are
integer-based value objects: `shift(n)` rolls over year boundaries without
drift, ordering is total within a kind and raises across kinds, and keys
(`FY2024Q3`, `FY2024`) round-trip through `parse_period`. `FiscalCalendar(
year_end_month)` maps periods onto calendar dates for an issuer's fiscal
year-end, which is where leap years enter (`days(FiscalYear(2024)) == 366`).

## Snapshot hashing and versioning

`GraphSnapshot.build(model_id, nodes)` produces `snapshot_id = sha256(canonical
JSON of {schema, model_id, version, parent_snapshot_id, scenario_id, nodes})`.
`derive()` / `with_nodes()` return a child (`version + 1`, `parent_snapshot_id`
set) and never mutate the parent; `verify()` recomputes the hash. The canonical
encoder is *typed*: `Decimal` → `{"$decimal": "1.5"}` (representation
independent, so `1.50` and `1.5` agree), `datetime` → UTC ISO under
`$datetime`, dataclasses → `{"$type": ClassName, ...}`; `$`-prefixed keys are
reserved and rejected in user data, floats and naive datetimes are rejected,
and `None` is JSON `null` — never a sentinel string. `test_canonical.py` and
`test_result_ids.py` carry the adversarial cases (delimiter forgery,
None-vs-sentinel, one-ulp value change, rescaling, tz-equivalent stamps,
operand order, string/Decimal type confusion).

`SnapshotStore` is a Protocol (`put`/`get`/`lineage`/`versions`);
`InMemorySnapshotStore` verifies the content hash on write, is idempotent for
identical content, and refuses orphans (parent must be stored first).

## Evaluation

`evaluate(snapshot, cutoff=..., sink=None)` walks the topological order once:

- leaves must have `as_of <= cutoff` (forecast leaves also
  `dataset_cutoff <= cutoff`) or the run raises `TEMPORAL_SCOPE_VIOLATION`
  (Constitution I); a naive cutoff is itself a violation;
- a derived node's `available_at` is `max(parents' available_at)` — derived
  nodes have no `as_of` field, so a caller cannot claim one;
- `result_id = sha256({cutoff, inputs: [parent result ids], node: definition,
  schema})` with the node definition pre-encoded once per graph. Identity is
  recursive: changing one source fact re-keys exactly its transitive
  dependents; everything else keeps its id (the scenario tests assert this);
- `CalcResult` (frozen) carries value, unit, period, provenance, `Lineage`,
  `input_result_ids`, `available_at`, `formula_version` and — for checks —
  `passed`. `EvaluationResult.results` is read-only; `failed_checks` lists
  failing validation nodes in order; `trace(node_id)` walks provenance back
  to source spans and assumptions. Checks report; they do not halt.

## Scenarios

`Scenario.of(scenario_id, label, {node_id: Decimal}, as_of=...)` is a sparse,
sorted, immutable override set. `apply_scenario(base, scenario)` derives a
child snapshot in which each override becomes a `ScenarioOverrideNode`
shadowing the *effective* target (so scenarios layer) and every consumer of
that target is re-pointed at the override; the base snapshot is untouched and
unaffected sub-graphs keep identical result ids. Only assumptions and drivers
are overridable (`SCENARIO_ERROR` otherwise).

## Telemetry

Structured, redacted events via `fel_calculation_engine.telemetry` (default
sink: one `logging` line `calc_telemetry {...}` on
`fel_calculation_engine.telemetry`; inject a `TelemetrySink` to capture):

| Event | Fields |
|---|---|
| `calc.evaluate.started` | `snapshot_id`, `cutoff`, `node_count`, `edge_count` |
| `calc.evaluate.completed` | + `evaluation_id`, `result_count`, `failed_check_count`, `duration_ms` |
| `calc.evaluate.failed` | `snapshot_id`, `error_code`, `node_id`, `duration_ms` |
| `calc.scenario.applied` | `base_snapshot_id`, `snapshot_id`, `scenario_id`, `override_count`, `node_count` |
| `calc.snapshot.stored` | `snapshot_id`, `model_id`, `version`, `parent_snapshot_id`, `scenario_id`, `node_count` |

Redaction is unconditional: `value`/`values`/`label`/`text`/`prompt`/secret-like
keys are masked and strings over 256 characters truncated. No node value or
label ever reaches a sink.

## Benchmark method (T0410)

`build_synthetic_model(5000, seed=63)` yields exactly 5,000 nodes covering all
nine kinds (per segment: price and units facts, a driver, revenue, a
cost-ratio assumption, cost, gross profit, a validation check, a reported
output and a forecast leaf; a fiscal-year rollup every four quarterly
segments; a scenario override every eighth). `test_benchmark_recalc.py` builds
the snapshot once, warms up, then times 11 full recalculations (`gc.collect()`
before each) and asserts the p95 (nearest-rank) is under the spec budget of
**< 500 ms** for "Model recalculation, 5k nodes" (spec §16.1). Measured on the
development machine (Python 3.11.14, Apple silicon): **p95 43.2 ms, median
42.0 ms**. Run with `-s` to print the measurement:

```bash
.venv/bin/pytest packages/calculation-engine/tests/test_benchmark_recalc.py -p no:warnings -s
```

## Limitations

- **No persistence.** M4 tables do not exist yet (#197) and `db/migrations`
  is a shared path; `InMemorySnapshotStore` is the reference behaviour a
  Postgres-backed store must reproduce. Adding one is a separate
  `contract-change`.
- **Property tests use a seeded `random.Random` generator**, not
  `hypothesis`: it is not in `requirements-dev.txt` and adding a dependency
  is outside ADR-0008. Adopting it is an integration-lead decision.
- **No memoization across evaluations.** Result ids make an unchanged
  sub-graph provably identical, but `evaluate()` recomputes every node; the
  benchmark is a full recalculation.
- **`count` is absorbed by `currency`** (`currency * count * count` is still
  `currency`); the algebra does not track count powers.
- **Periods are integer-based**; issuer 4-4-5 / 52-53-week calendars are not
  modelled beyond `FiscalCalendar(year_end_month)`.
- **The ISO 4217 minor-unit table is static** (2024 list); unknown codes
  require an explicit `quantum`.
- **No valuation formulas.** The issue checklist's "WACC ≤ growth" item is
  covered at the mechanism level (a `greater_or_equal` check plus fail-closed
  division), not by a DCF node kind, which is outside the approved node set.
- **Scenario overrides target assumptions and drivers only**; overriding a
  source fact is refused by design (reported values are immutable).
