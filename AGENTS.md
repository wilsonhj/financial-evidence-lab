# Agent operating contract

This repository is designed for parallel implementation by Codex, Claude Code, and other Git-capable agents coordinated by Fable.

## Read before changing code

1. `.specify/memory/constitution.md`
2. `specs/001-financial-evidence-lab/spec.md`
3. `specs/001-financial-evidence-lab/plan.md`
4. `specs/001-financial-evidence-lab/tasks.md`
5. `docs/handoff/README.md`
6. `docs/handoff/workstreams.yaml`

The feature directory `specs/001-financial-evidence-lab/` holds the sole canonical `spec.md`, `plan.md`, and `tasks.md`. Root `SPEC.md`, `PLAN.md`, and `TASKS.md` are pointer stubs only — never edit or cite them as sources. The locked MVP stack lives in `docs/decisions/ADR-0002-mvp-stack.md`.

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

Changes to a shared path require an ADR, the `contract-change` label, and integration-lead review.

## Completion protocol

Before yielding, push the branch and update the PR with the current commit SHA, tests, blockers, and next action. The durable state is GitHub plus the committed handoff files; chat history is never the source of truth.
