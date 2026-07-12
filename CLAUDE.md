# Claude Code bootstrap

Follow `AGENTS.md` as the repository-wide operating contract.

## Resume sequence

1. Read `docs/handoff/STATUS.md` and `docs/handoff/workstreams.yaml`.
2. Confirm the assigned GitHub issue, branch, base SHA, dependencies, and allowed paths.
3. Read only the relevant portions of the constitution, spec, plan, and task list.
4. Check out the assigned branch in a dedicated worktree.
5. Run the package-specific baseline checks before editing.
6. Implement the smallest acceptance-complete change and open or update a draft PR.

Do not redesign approved architecture. Do not change a shared contract, schema, migration, lockfile, authentication boundary, or cross-package interface unless the issue is labeled `contract-change` and links an accepted ADR.

If blocked, leave the branch buildable, push a checkpoint, and document: failing command, relevant output, attempted remedies, required decision or credential, and exact next action.

Fable orchestration instructions are in `docs/handoff/FABLE_ORCHESTRATION.md`.
