# ADR-0008: New first-party package scaffold wiring rides with the owning package

Status: Proposed
Date: 2026-07-19
Accepted: (on merge by integration lead)
Occasioned by: M2-RETRIEVAL-BACKEND (#57); recurs for every future first-party package
Amends: ADR-0003 (root-config-edits)

## Decision

Extend the ADR-0003 mechanical-consequence exception to cover the shared
build/test/CI registration files that a **new first-party package** must
touch to become visible to the shared quality gates. When a package's core
deliverable is a new directory under `packages/**` (or an equivalent new
first-party module tree), its PR may include the **scaffold-registration**
edits that wire that directory — and only that directory — into the gates,
without a separate `contract-change` issue and ADR, when **all four ADR-0003
conditions hold** (mechanical consequence of the in-scope package; no
contract/schema/migration/auth change; each hunk itemized as a flagged
deviation in the PR Scope; integration lead records the authorization
durably on the work-package issue before the PR leaves draft).

The registration files now in scope of the exception, in addition to the
ADR-0003 JS set:

- **`pyproject.toml`** — adding the new package directory to
  `[tool.ruff] src`, `[tool.mypy] mypy_path`, `[tool.pytest.ini_options]
  pythonpath`, and its `tests/` dir to `testpaths`.
- **`Makefile`** — adding the new package directory to the `black` / `ruff`
  / `mypy` / `bandit` target lists.
- **`.github/workflows/ci.yml`** — adding the same directories to the
  `python` job's `black` / `ruff` / `mypy` / `bandit` run lines.

These are pure additive dir-list registrations: they change no existing
package's build or test behavior, and omitting them leaves the new
package's branch unbuildable (its code is linted/typed/tested by nothing),
violating the "leave the branch buildable" resume contract exactly as the
ADR-0003 JS case did.

## Explicitly NOT covered

- **`requirements-dev.txt`** (and any runtime/dev **dependency** addition).
  Adding a dependency is a supply-chain and behavior change, not mechanical
  scaffolding; it remains a per-dispatch integration-lead authorization (or
  the full contract-change process). A new package that needs a runtime dep
  requests it separately, by name, when justified.
- Toolchain upgrades, workspace-layout restructuring, or any edit to these
  files not forced by registering the single in-scope new package. Those
  remain full shared-path changes.
- `.github/**` edits beyond the `python` job's dir-list registration (new
  jobs, service images, secrets, workflow triggers) remain shared and
  require separate authorization — the exception is the narrow dir-list
  addition only.

## Context

ADR-0003 converted a JS precedent-by-exception (M1-EVIDENCE-UI's Next.js
root edits) into a bounded standing rule, but its `applies_to` deliberately
listed only the five JS workspace files, because M0 was JS-first. Every
subsequent **Python** package hits the identical wall: `packages/providers`
was scaffolded during M0 inside the platform package, but each new
first-party Python tree — `packages/retrieval` (#57), and ahead of it
`packages/ontology` (#60), `packages/calculation-engine` (#63),
`packages/retrieval-evals` (#58), `packages/export` (#68),
`packages/observability` — must register itself in the same three shared
files or fail `make ci` on its first commit. The `packages/retrieval`
registration was pre-authorized as a one-off per-dispatch grant on issue
#57 (integration-lead comment, 2026-07-19); this ADR generalizes that grant
so the identical mechanical wiring is not relitigated per package.

The machine-readable encoding lands with acceptance: `workstreams.yaml`
`shared_path_exceptions` gains a second entry naming this ADR, its
`applies_to` files (`pyproject.toml`, `Makefile`,
`.github/workflows/ci.yml`), and the rule
`new-first-party-package-scaffold-registration-only`. Automated
dispatch/review continues to treat every `shared_paths` entry as shared;
this exception, like ADR-0003's, is judged per-hunk at review time against
the four conditions.

## Consequences

- New-package PRs stay self-contained and buildable; reviewers evaluate the
  three registration files against the four conditions instead of
  relitigating process for each package.
- Runtime dependency additions stay gated — the risky supply-chain surface
  is not swept into the mechanical exception.
- The `contract-change`/agent-task issue comment remains the durable
  per-instance authorization record.
- Any scaffold edit failing a condition (touches another package's dirs,
  adds a dependency, restructures the toolchain) is a process violation to
  raise on the PR, not merge.

## Revisit triggers

- A new package needs a build-graph change beyond dir-list registration
  (e.g. a new CI job or service): out of scope; requires its own
  authorization.
- The Python packaging model changes (e.g. adopting installed workspace
  packages instead of path-based `mypy_path`/`pythonpath` wiring): revisit
  the registration surface this exception enumerates.
