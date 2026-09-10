# ADR-0018: Formula AST and explicit iterative calculation groups

Status: Accepted for implementation by the integration lead under the owner's
request to implement the complete open-issue plan; independent design reviewed.

Date: 2026-09-10

Issue: #219. Parent: specification §8.5 and FR-MOD-002.

## Scope

Retain both requirements: user-authored formulas become a typed AST, and cycles
are allowed only when explicitly modeled as iterative groups. Neither is
deferred. Extend the existing Decimal calculation engine; introduce no provider,
framework, service, database or public HTTP contract. T0411 and T0412 are added
unchecked to the sole canonical ledger. Their presence is not completion.

## Restricted formula language

Grammar v1 admits bracketed node references, finite Decimal literals, unary
plus/minus, binary addition/subtraction/multiplication/division, parentheses and
ordinary precedence. Brackets preserve existing node IDs containing punctuation.
Calls, attributes, strings, indexing, arbitrary identifiers and executable code
are rejected. No eval, exec, compile, floating-point conversion or reassociation.

Use immutable closed reference/literal/unary/binary AST variants. Parse at
construction, validate direct AST construction too, and evaluate only that AST.
Limits are 4,096 input characters, 512 AST nodes and depth 64. Errors are typed
and include an offset when parsing text. Literal bounds follow the existing
Decimal value constraints. Canonical AST serialization includes grammar and
formula versions; insignificant whitespace does not change execution identity.

Literals are dimensionless ratios. Currency/count values enter through explicit
source or assumption nodes. Require at least one reference; constant assumptions
already have a node kind. Repeated AST references stay repeated in arithmetic
but appear once in dependency/lineage lists. Graph validation decides whether a
self-reference is authorized. Existing operator-based FormulaNode construction
remains compatible; expression nodes are a separate valid shape.

Infer units recursively, validate the declared result unit, and retain existing
fiscal-period-kind compatibility. All arithmetic, including unary negation and
convergence checks, uses the pinned 34-digit ROUND_HALF_EVEN context. Reporting
nodes retain the sole reporting-quantization boundary.

## Explicit iteration policy

Each immutable group declares its ID, member IDs, an external seed node for
every member, absolute tolerance per member, relative tolerance, and iteration
cap. There are no implicit seeds, tolerances or caps. Seeds must match the
member's unit and exact period and satisfy the cutoff. They cannot depend on
the group. Tolerances are finite/nonnegative, with a positive absolute or
relative tolerance for every member. Caps are integers from 1 through 1,000;
booleans are rejected. Absolute tolerances use each member's unit.

Compute strongly connected components without recursion. Every cyclic component
(including a self-cycle) must exactly match one declared group. Reject absent,
overlapping, partial, superset and acyclic declarations, and cycles introduced
through seed dependencies. Iterative members are arithmetic formula nodes;
checks and reporting quantization remain downstream. Execute the condensed DAG
in stable ID order, with sorted group members.

Use Jacobi updates: every next value reads the complete previous vector. After
each completed sweep, require every member to satisfy:

```
abs(new - old) <= absolute_tolerance + relative_tolerance * max(abs(new), abs(old))
```

Return the first complete vector meeting all tolerances. No damping, random
order, cached warm-start or best-effort result is implicit. Arithmetic failure
aborts immediately. Cap exhaustion raises a typed convergence error containing
group ID, completed sweeps and deterministic residuals. Downstream evaluation
does not run and no successful authoritative result is published on failure.

## Provenance and compatibility

A circular model cannot hash every result from its final parents' result hashes.
Instead hash one immutable iteration execution record containing algorithm/
schema version, member definitions, policy, seed and external result IDs, cutoff,
iteration count, final typed vector and residuals. Internal equation references
are node IDs. Derive each member result ID from this execution ID and member ID.
Do not include unrelated snapshot content or timing in execution identity.

Each iterative result links to the execution record and the unique union of
the group's seed/external result IDs. The execution record retains internal
equations separately, so tracing follows a provenance DAG without claiming that
Jacobi used the final same-sweep vector as its input. Every trace ID resolves.
Availability is the maximum seed/external availability, even when a seed's
numeric effect disappears after convergence.

Snapshot policies and seed references are immutable and included in new-feature
snapshot identity. Rebuild, derive, restore and scenario operations preserve and
revalidate them; reference rewrites operate on AST structure and seed mappings.
Version new payload shapes. Preserve exact legacy payloads and hashes for graphs
without expressions or groups. Unrelated node edits or relabeling do not alter
group result identity; seed, policy, equation, external input or cutoff changes do.

## Verification and limits

Tests cover grammar/injection/resource limits, units and periods, repeated
references, legacy compatibility, explicit self/two-node cycles, invalid group
and seed graphs, convergence thresholds, oscillation/divergence, later-sweep
division by zero, Decimal-context independence, shuffled insertion order,
lineage/cutoff integrity, scenarios and restore. Preserve the existing 5,000-node
DAG performance gate and add separately declared iterative measurements; this
ADR does not promise arbitrary 1,000-sweep models meet the one-pass DAG budget.

Caller-chosen tolerances remain visible model policy, not a financial accuracy
waiver. Live milestone acceptance, model persistence/UI and release evidence
remain owned by their existing issues. Independent implementation review and
current CI precede merge; the lead checks canonical tasks only after verification.
