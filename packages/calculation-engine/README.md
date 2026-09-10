# `@fel/calculation-engine` (`fel_calculation_engine`)

Server-side Decimal calculation engine for the Revenue Model Composer
(spec §8.5, FR-MOD-001 / FR-MOD-002). Authoritative math is Decimal-only,
typed-unit, and deterministic. Language models must not execute it.

## What it does

- Nine node kinds (source fact, assumption, driver, formula, aggregation,
  scenario override, forecast output, validation check, reported output)
- Bounded typed formula ASTs and opt-in exact-SCC iterative groups
- Fail-closed cycle detection and versioned, content-addressed snapshots
- Decimal arithmetic under `CALC_CONTEXT` (34 digits, banker's rounding)
- Closed unit algebra, typed fiscal periods, percent → ratio normalization
- Provenance retained through recalculation; derived cutoffs are `max(parents)`
- Property tests and a deterministic 5,000-node recalculation benchmark (opt-in)

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
| `formulas.py`, `iteration.py` | T0411 / T0412 | Restricted immutable arithmetic ASTs, explicit fixed-point policy and execution records |
| `tests/_gen.py`, `tests/test_properties.py` | T0409 | Seeded deterministic property tests |
| `synthetic.py`, `tests/test_benchmark_recalc.py` | T0410 | Deterministic 5,000-node model and the opt-in recalculation benchmark |

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
| `ExpressionFormulaNode` (same formula kind) | derived | immutable `ast`, `grammar_version`, `formula_version` | unique `reference[i]` |
| `AggregationNode` | derived | `operator` (`sum` same period / `rollup_year` Q1..Q4 → FY) | `operand[i]` |
| `ScenarioOverrideNode` | assumption | `value`, `as_of`, `scenario_id`, `assumption_id` | `overrides` |
| `ForecastModelOutputNode` | forecast | `value`, `as_of`, `forecast_run_id`, `dataset_cutoff`, `dataset_version` | — |
| `ValidationCheckNode` | derived | `check` (equals/non_negative/less_or_equal/greater_or_equal), `tolerance` | `operand[i]` |
| `ReportedFinancialOutputNode` | derived | `metric_id`, optional `quantum` | `source` |

Edges are derived from `Node.inputs()` plus each declared iteration seed
(`iteration_seed` role). `dependencies()` includes these seed execution
prerequisites; the original equation references remain in each node and
iteration record.
`ModelGraph.build()` fails closed on duplicate ids, dangling references
(`MISSING_INPUT`) and undeclared cycles (`CYCLE_DETECTED`, carrying a concrete
cycle path), and type-checks every derived node against its inputs before anything
is evaluated: formula unit algebra must reproduce the declared unit, formula
operands must share the output's period *kind*, `sum` operands share the
output period, `rollup_year` operands are exactly the four quarters of the
output year, drivers/outputs match their source's unit and period, and
overrides may only shadow assumptions, drivers or earlier overrides.

The Constitution II four-way split (reported / user-supplied / derived /
forecast) is `Provenance`; `Lineage` enforces exactly one lineage field per
kind (`source_span_id` / `assumption_id` / `derived_from` / `forecast_run_id`)
— never selected by an or-chain.

## User-authored formulas (ADR-0018)

`ExpressionFormulaNode.from_expression(..., expression="[revenue] * (1 + [growth])",
formula_version="v1")` parses once into frozen `Reference`, `Literal`, `Unary`
and `Binary` variants. `node.ast` is authoritative; `node.expression` generates
unambiguous display text from that tree. Direct AST construction has the same
closed-type, operator, literal and resource validation.

Grammar `fel-formula/v1` supports:

- bracketed node IDs, including punctuation: `[revenue.us:2024-Q1]`;
- finite Decimal literals (`2`, `.5`, `1.25e-3`), unary `+`/`-`, binary
  `+`, `-`, `*`, `/`, parentheses, and ordinary precedence/left associativity;
- at most 4,096 text characters, 512 AST occurrences and depth 64; parser
  nesting is also bounded at 64. Literal precision/exponent bounds match
  the canonical Decimal constraints (34 digits, exponent ±250,000).

There are no calls, attributes, indexing, arbitrary identifiers, strings,
comparisons, powers or executable code. Parsing failures raise `FormulaError`
with `details["offset"]`. Every formula must reference at least one node;
constants belong in assumption nodes. Literals are dimensionless `RATIO`s,
so `[revenue] + 1` is a unit error for currency revenue. Reference periods must
have the output's period kind; explicit different quarters remain supported.

`formula_dependencies(ast)` returns first-occurrence unique references.
`[x] + [x]` therefore doubles the value but has one dependency/lineage parent.
`evaluate_formula(ast, {node_id: Quantity})` uses the same typed arithmetic;
`rewrite_formula_references(ast, mapping)` rewrites leaves structurally.
Whitespace and equal Decimal spellings do not change execution identity;
operand order, AST structure, grammar and formula versions do.

## Explicit iterative groups (ADR-0018)

Every cyclic strongly connected component must exactly match one declared
`IterationGroup`; self-cycles are included. Partial, overlapping, superset,
duplicate or acyclic declarations are rejected with `IterationPolicyError`.
Only `FormulaNode` and `ExpressionFormulaNode` may be members. Reporting and
validation checks execute downstream. The graph's `execution_plan` contains
single node IDs or whole groups; `order` is its deterministic flattened order,
not a node topological order inside a cycle.

This example models interest on principal plus interest:

```python
from datetime import UTC, datetime
from decimal import Decimal
from fel_calculation_engine import (
    RATIO, AnalystAssumptionNode, ExpressionFormulaNode, FiscalQuarter,
    GraphSnapshot, IterationGroup, SourceFactNode, currency, evaluate,
)

stamp = datetime(2024, 5, 1, tzinfo=UTC)
period, usd = FiscalQuarter(2024, 1), currency("USD")
principal = SourceFactNode(
    node_id="principal", label="Principal", unit=usd, period=period,
    value=Decimal("1000"), as_of=stamp, source_span_id="filing-principal",
)
rate = AnalystAssumptionNode(
    node_id="rate", label="Rate", unit=RATIO, period=period,
    value=Decimal("0.1"), as_of=stamp, assumption_id="rate-policy",
)
seed = AnalystAssumptionNode(
    node_id="seed", label="Initial interest", unit=usd, period=period,
    value=Decimal("0"), as_of=stamp, assumption_id="initial-interest",
)
interest = ExpressionFormulaNode.from_expression(
    node_id="interest", label="Interest", unit=usd, period=period,
    expression="([principal] + [interest]) * [rate]", formula_version="interest-v1",
)
policy = IterationGroup.of(
    group_id="interest-cycle", members=("interest",), seeds={"interest": "seed"},
    absolute_tolerances={"interest": Decimal("0.01")},
    relative_tolerance=Decimal("0"), max_iterations=100,
)
snapshot = GraphSnapshot.build(
    "interest-model", [principal, rate, seed, interest], iteration_groups=(policy,),
)
run = evaluate(snapshot, cutoff=stamp)
assert run.quantity("interest").value == Decimal("111.11")
result = run.result("interest")
record = run.iteration_runs[result.iteration_run_id]
assert record.iterations == 5 and record.verify()
assert {item.node_id for item in run.trace("interest")} == {
    "interest", "principal", "rate", "seed",
}
```

`IterationGroup.of` copies mappings into sorted immutable pair tuples. Every
member requires an external seed **node ID**, absolute tolerance in its own
unit, and positive absolute or relative tolerance. Relative tolerance is a
shared dimensionless Decimal; the explicit integer cap is 1–1,000 (booleans
are rejected). Seeds must match the member's exact unit and fiscal period,
satisfy cutoff rules, and cannot depend on the group, even transitively through
another group's seed. No seed, tolerance or cap is inferred.

Every sweep uses the entire previous vector (Jacobi). After a completed sweep,
every member must satisfy:

```text
abs(new - old) <= absolute_tolerance + relative_tolerance * max(abs(new), abs(old))
```

All arithmetic and convergence checks use the pinned 34-digit context.
The first complete qualifying vector is returned. Arithmetic failures abort
immediately. Cap exhaustion raises `IterationConvergenceError` with group ID,
completed sweeps and deterministic residuals. Downstream nodes do not execute,
and no successful evaluation or authoritative partial vector is published.
Tolerances are visible model policy; they are not reporting quantization or
a guarantee that the model's equations have a unique fixed point.

### Iterative provenance and version compatibility

An `IterationRun` hashes the algorithm/schema, label-free member definitions,
internal dependency node IDs, complete policy, seed/external result IDs,
normalized cutoff, completed sweeps, final typed vector and residuals. Each
member result ID hashes that run ID plus member ID. This avoids recursive
hash cycles and does not include unrelated snapshot content or timing.

Each member's `iteration_run_id` resolves in `EvaluationResult.iteration_runs`.
Its lineage/input result IDs are the unique group seed/external parents;
`trace()` follows this provenance DAG back to real results. The record retains
internal equations separately because Jacobi consumed the previous vector,
not the final same-sweep values. Availability is the maximum across **all**
seed/external results, even when convergence erases a seed's numeric effect.

Expression/group snapshots use `fel-calc-snapshot/v2`, including immutable
iteration policies, and evaluations use `fel-calc-evaluation/v2`. Expression
and iterative results expose `fel-calc-result/v2`; iterative identity has its
own `fel-calc-iterative-result/v1` domain. Graphs without these features retain
exact v1 snapshot/evaluation hashes and canonical result payloads, checked
against a golden fixture generated from the pre-feature engine.

`build(parent=...)`, `derive()` and `with_nodes()` preserve policies by default;
`iteration_groups=...` explicitly replaces them and revalidates the graph.
Scenarios rewrite AST references and seed IDs while preserving tolerance/cap
policy. To restore saved nodes **and their original policy**, use
`child.derive(saved.nodes, iteration_groups=saved.iteration_groups)`. The saved
snapshot remains immutable in the existing snapshot store.

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

`evaluate(snapshot, cutoff=..., sink=None)` executes the stable condensed DAG.
Without iterative groups this is the original single topological pass:

- leaves must have `as_of <= cutoff` (forecast leaves also
  `dataset_cutoff <= cutoff`) or the run raises `TEMPORAL_SCOPE_VIOLATION`
  (Constitution I); a naive cutoff is itself a violation;
- a derived node's `available_at` is `max(parents' available_at)` — derived
  nodes have no `as_of` field, so a caller cannot claim one;
- `result_id = sha256({cutoff, inputs: [parent result ids], node: definition,
  schema})` with the node definition pre-encoded once per graph. Identity is
  recursive for acyclic nodes: changing one source fact re-keys exactly its transitive
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
| `calc.iteration.started` | `group_id`, `algorithm`, `max_iterations`, `member_count` |
| `calc.iteration.completed` | `group_id`, `run_id`, `algorithm`, `max_iterations`, `iterations` |
| `calc.iteration.failed` | `group_id`, `algorithm`, `max_iterations`, `iterations`, `error_code` |
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
before each) and asserts the **slowest** of them is under the spec budget of
**< 500 ms** for "Model recalculation, 5k nodes" (spec §16.1). Measured on the
development machine (Python 3.11.14, Apple silicon): **slowest 43.2 ms, median
42.0 ms**.

The statistic is the maximum and is named that way. Nearest-rank p95 over 11
samples resolves to index 10 — the last element — so the original `_p95` helper
returned the maximum while claiming a percentile; the formula does not yield an
interior statistic below 21 samples. Reporting the maximum is the stricter
claim, so the budget check is unchanged.

**The timing assertion is opt-in and does not run in CI:**

```bash
FEL_RUN_BENCHMARKS=1 .venv/bin/pytest packages/calculation-engine/tests/test_benchmark_recalc.py -p no:warnings
```

Without that variable the timing test skips and only the determinism and
node-kind coverage checks run. A wall-clock assertion on a shared runner flakes:
review of PR #212 measured **322 ms** under 3x CPU oversubscription on hardware
faster than a GitHub runner, against the same 500 ms gate, with the engine
unchanged. The measurement is now carried in the assertion message rather than a
`print`, because `addopts` includes `-q` and printed output never reaches a CI
log.

Note also that the spec's target is a p95 under 25 concurrent users on the
§16.1 reference profile. This single-process proxy does not reproduce that
profile, so a green run here is evidence of no gross regression, not of the
spec target being met.

The separate `test_benchmark_iteration.py` proxy measures 100 arithmetic
members for exactly 24 Jacobi sweeps (101 nodes including the seed), with its
own 11-run maximum below 500 ms check. It does not modify the 5,000-node DAG
gate or promise arbitrary 1,000-sweep models meet that budget. Run both with:

```bash
FEL_RUN_BENCHMARKS=1 pytest packages/calculation-engine/tests
```

Current no-credential acceptance evidence is in
[`ACCEPTANCE-219.md`](ACCEPTANCE-219.md).

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
