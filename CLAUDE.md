# Claude Code bootstrap

Follow `AGENTS.md` as the repository-wide operating contract.

## Resume sequence

To resume assigned work, follow the single resume sequence in [`docs/handoff/README.md`](docs/handoff/README.md#resume-sequence): reconcile `STATUS.md` and `workstreams.yaml` against GitHub, confirm the assigned issue and allowed paths, work in a dedicated worktree, and open or update a draft PR. A first session in this repository follows the reading order in [`AGENTS.md`](AGENTS.md#read-before-changing-code) first.

Do not redesign approved architecture. Do not change a shared contract, schema, migration, lockfile, authentication boundary, or cross-package interface unless the issue is labeled `contract-change` and links an accepted ADR.

If blocked, leave the branch buildable, push a checkpoint, and document: failing command, relevant output, attempted remedies, required decision or credential, and exact next action.

Fable orchestration instructions are in `docs/handoff/FABLE_ORCHESTRATION.md`.
