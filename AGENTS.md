# Agent operating contract

This repository is designed for parallel implementation by Codex, Claude Code, and other Git-capable agents coordinated by Fable.

## Read before changing code

1. `.specify/memory/constitution.md`
2. `specs/001-financial-evidence-lab/spec.md`
3. `specs/001-financial-evidence-lab/plan.md`
4. `specs/001-financial-evidence-lab/tasks.md`
5. `docs/handoff/README.md`
6. `docs/handoff/workstreams.yaml`

The feature directory `specs/001-financial-evidence-lab/` holds the **sole canonical task ledger** (`tasks.md`) plus the parent `spec.md` and `plan.md`. There is exactly one ledger — never restate the `T####` list or its completion state anywhere else. Milestone and completion directories (`specs/002-*` onward) may hold subordinate `spec.md`, `plan.md`, and milestone-scoped `tasks.md` whose IDs map onto the canonical `T####` IDs; each names its parent, and the parent governs on conflict. Root `SPEC.md`, `PLAN.md`, and `TASKS.md` are pointer stubs only — never edit or cite them as sources. The locked MVP stack lives in `docs/decisions/ADR-0002-mvp-stack.md`.

## Working rules

- Work on exactly one GitHub issue and one branch per worktree.
- Use branch names from `docs/handoff/workstreams.yaml`.
- Stay inside the issue's `allowed_paths`. Do not edit `shared_paths` without an approved `contract-change` issue and ADR.
- Build against committed mocks and fixtures. Never put credentials in prompts, issues, commits, logs, fixtures, or PR text.
- Open a draft PR early. Push bounded checkpoints so another agent can resume.
- Include task IDs, acceptance evidence, tests run, current limitations, and any credential request in the PR.
- Agents do not mark Spec Kit tasks complete. The integration lead checks tasks only after merge and verification.
- Deterministic financial calculations, temporal cutoffs, tenant isolation, and citation integrity must be enforced by code and tests, not model judgment.

## Shared paths

The integration lead owns these paths:

- `.github/`
- `.specify/`
- `specs/`
- root package/lock/config files
- `packages/contracts/`
- `db/migrations/`
- `docs/decisions/`
- `docs/handoff/workstreams.yaml`
- `docs/handoff/STATUS.md`

Every change to a shared path requires the `contract-change` label and
integration-lead review. Whether it also requires an accepted ADR depends on
the class of change, per the integration-lead ruling on #141 (2026-08-29,
addended 2026-09-03):

| Class | Required | ADR? |
|---|---|---|
| Contracts, migrations, `specs/**`, `docs/decisions/**` | `contract-change` + accepted ADR + lead review | Yes |
| The canonical task ledger — checkbox state and per-task annotations in `specs/001-financial-evidence-lab/tasks.md` | `contract-change` + lead review | No, unless a dispatch key / dependency / credential policy changes |
| Handoff ledger (`workstreams.yaml`, `STATUS.md`) | `contract-change` + lead review | No, unless a dispatch key / dependency / credential policy changes |
| Advisory / lockfile / workspace pin | `contract-change` label + authorization record on the PR | No full ADR. These pin transitive versions rather than changing a shared contract. |

The task-ledger row is deliberately narrow. It covers `[ ]`/`[x]` state and the
sentence appended to a task line recording why it was or was not checked.
**Changing a task's text, its ID or its ordering, adding or removing a task, and
adding, retitling or deleting a spec document all stay in row 1 and need the
ADR.** It is not a general `specs/**` carve-out.

An "authorization record" is a statement on the PR, by the integration lead,
naming what is being authorized and why. The label is required in every row so
that a single CI check can enforce the whole table; that check is still unbuilt
(#141).

## Completion protocol

Before yielding, push the branch and update the PR with the current commit SHA, tests, blockers, and next action. The durable state is GitHub plus the committed handoff files; chat history is never the source of truth.
