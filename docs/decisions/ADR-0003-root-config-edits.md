# ADR-0003: Mechanical root-config edits ride with the owning package

Status: Proposed (drafted for integration-lead acceptance; occasioned by PR #79 / issue #55)
Date: 2026-07-13

## Decision

A work package whose in-scope change mechanically requires edits to root
package/lock/config files (`package.json`, `pnpm-lock.yaml`,
`pnpm-workspace.yaml`, `tsconfig.json`, and equivalents) may include those
edits in its own PR, without a separate `contract-change` issue and ADR,
when **all** of the following hold:

1. The root edit is a mechanical consequence of an in-scope change (a
   dependency addition inside the package's `allowed_paths`, a build-graph
   entry for the package's own directory, or a security override needed to
   keep the CI audit gate green against a transitively pinned CVE).
2. It changes no contract, schema, migration, or authentication boundary.
3. Each root-file hunk is itemized in the PR's Scope section as a flagged
   deviation, with its mechanical justification.
4. The integration lead records the authorization durably on the work-package
   issue before the PR leaves draft (chat history is never the source of
   truth).

Standalone root-config changes — anything not forced by an in-scope change,
including dependency-graph restructuring, toolchain upgrades, and workspace
layout changes — remain full shared-path changes requiring a
`contract-change` issue, an ADR, and integration-lead review.

## Shared-path list reconciliation

`AGENTS.md` lists "root package/lock/config files" as integration-lead-owned
shared paths; `docs/handoff/workstreams.yaml` `shared_paths` omits them. The
two lists are reconciled as follows: **AGENTS.md governs.** Root
package/lock/config files are shared paths; this ADR is the standing,
narrowly-scoped authorization for the mechanical subset defined above.
`workstreams.yaml` `shared_paths` remains the machine-readable list of paths
that are shared *and* have no standing authorization.

## Context

M1-EVIDENCE-UI (PR #79, issue #55, task T0110) introduced the Next.js
runtime in `apps/web` — that package's core deliverable — which mechanically
required four root edits outside its `allowed_paths`
(`apps/web/**`, `packages/ui/**`):

- `tsconfig.json`: `apps/web` removed from the composite `tsc -b` reference
  graph (Next.js `noEmit`/plugin conventions conflict with composite emit);
  typecheck coverage preserved via the root script change below.
- `package.json`: root `typecheck` extended to
  `tsc -b && pnpm --filter @fel/web typecheck`, keeping the web app inside
  the CI gate.
- `pnpm-workspace.yaml`: `overrides: postcss: "^8.5.10"` — next@16.2.10 pins
  postcss 8.4.31 (GHSA-qx2v-qp2m-jg93), which fails the `pnpm audit` step of
  `make ci`; the override exists solely to keep the security gate green.
- `pnpm-lock.yaml`: mechanical consequence of the in-scope `apps/web`
  dependency additions.

All four satisfy conditions 1–3; the integration lead's authorization record
is published at issue #55 (comment of 2026-07-13). Splitting the edits into
a separate PR would leave the package branch unbuildable, violating the
"leave the branch buildable" requirement.

This situation recurs with every milestone package that adds dependencies;
this ADR converts a precedent-by-exception into a bounded standing rule.

## Consequences

- Package PRs stay self-contained and buildable; reviewers evaluate the
  root hunks against the four conditions instead of relitigating process.
- The `contract-change` label on the work-package issue plus the issue
  comment remain the durable per-instance record.
- Any root edit failing a condition is a process violation to be raised on
  the PR, not merged.
