# Issue #219: local implementation acceptance evidence

Date: 2026-09-10. Scope: both retained specification §8.5 requirements under
accepted ADR-0018: typed arithmetic formula ASTs and explicit iterative groups.
No credentials, network providers, paid calls, database or UI are involved.
This evidence does not mark canonical tasks complete or establish live M4 acceptance.

## Verification

Using the existing project virtual environment, Python 3.11.16 on
macOS 26.6.2 arm64:

```text
FEL_RUN_BENCHMARKS=1 python -m pytest packages/calculation-engine/tests
233 passed in 1.78s

ruff check packages/calculation-engine
All checks passed!

mypy packages/calculation-engine/fel_calculation_engine
Success: no issues found in 17 source files

black --check packages/calculation-engine
git diff --check
```

The README's executable financial example was also run successfully.

Test-first checkpoints: 28 parser tests failed for the missing parser before
implementation (`65abae5`), then 31 group tests failed for the missing iteration
policy before implementation (`4ce5a17`). Subsequent failing regressions caught
and fixed legacy canonical result-payload drift, untyped enormous-exponent
errors, provenance-finalization failure telemetry, seed dependency inspection,
and explicit evaluation schema exposure. Golden v1 snapshot/evaluation IDs and
canonical result-payload hashes were generated from the unchanged engine at
`4685697`, not from the new serializer.

Coverage includes grammar and injection rejection, AST closure/resource bounds,
Decimal precision/exponent/unary behavior, units and period kinds, repeated
references, exact SCC declarations, malformed policies, transitive seed cycles,
seed unit/period/cutoff failures, simultaneous Jacobi updates, all-member
convergence and exact tolerance boundaries, mixed units, relative tolerance,
oscillation/divergence/cap exhaustion, later-sweep division by zero, 34-digit
ties, seeded generated arithmetic and contraction properties, shuffled graph
order, local execution identity, immutable provenance, tracing, scenario
rewrites and snapshot restoration. A 5,000-member SCC test exercises
nonrecursive construction, evaluation and trace traversal.

## Controlled performance measurements

Measured at implementation checkpoint `b741daa` with one warm-up, 11 timed
full evaluations, graph construction outside the timer, and `gc.collect()`
before each run. The existing DAG test and its **< 500 ms** gate were unchanged.
Final verification above reran both gates after the evaluation schema field was
exposed; that field does not alter calculation semantics.

| Fixture | Nodes | Median | Nearest-rank p95 / maximum of 11 |
|---|---:|---:|---:|
| Existing nine-kind synthetic DAG, seed 63 | 5,000 | 31.486 ms | 31.934 ms |
| Separate 100-member ring, exactly 24 Jacobi sweeps | 101 | 9.138 ms | 9.331 ms |

DAG samples (ms): 31.414, 31.576, 31.415, 31.491, 31.867, 31.934,
30.932, 31.330, 31.509, 31.486, 31.432.

Iterative samples (ms): 9.331, 9.134, 8.929, 9.055, 9.158, 9.129,
9.191, 9.142, 9.130, 9.138, 9.184.

With 11 samples the nearest-rank p95 is the maximum. These are single-process
local proxies; they do not reproduce the specification's 25-concurrent-user
reference profile. The bounded iterative measurement is separate and does not
promise arbitrary 1,000-sweep models meet the one-pass DAG budget.

## Integration boundary

The existing stack, operator formulas, reporting quantization, sparse scenario
permissions and legacy v1 identities remain intact. Policies and seed lineage
are explicit; failed iteration publishes no successful partial result. HTTP,
DB persistence, graph UI and live release evidence remain separate issues.
Independent implementation review and current CI are required before merge;
only the integration lead updates canonical completion state after verification.

## CI security follow-up

The first final CI run reported four low-severity Bandit findings: two
assertions used only for constructor-proven type narrowing, and two false
positives treating the lexer's `token` character comparisons as hardcoded
passwords. Replaced the assertions with static casts after the existing graph
validation and renamed the character variable; no validation was removed and
no suppression was added. The complete CI Bandit command passed afterward:

```text
bandit -q -r apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology packages/calculation-engine scripts -c pyproject.toml
```

Focused parser, iteration and generated-property suites: 86 passed in 0.43s.
Strict engine mypy, Ruff and Black checks also passed.
