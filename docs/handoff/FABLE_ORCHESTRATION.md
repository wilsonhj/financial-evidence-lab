# Fable orchestration protocol

Fable is the scheduler and recovery coordinator; Claude Code agents are isolated workers. Fable does not make product architecture decisions or merge code.

## Scheduling loop

1. Load `workstreams.yaml`, `STATUS.md`, and GitHub issue/PR state.
2. Mark a package ready only when all dependencies are merged and paths do not overlap active work.
3. Create one worktree and the declared branch for one Claude Code agent.
4. Give the agent its issue, task IDs, allowed paths, frozen inputs, acceptance checks, and credential policy.
5. Require a draft PR and first pushed checkpoint before scheduling another risky package.
6. Poll PR checks and issue heartbeats. Record blockers in GitHub, not private orchestration memory.
7. Send passing PRs to an independent reviewer and then the integration lead.
8. After merge, ask the integration lead to update task checkboxes, package status, and `STATUS.md`.

## Worker prompt

```text
Repository: wilsonhj/financial-evidence-lab
Package: <id>
Issue: <url>
Base branch/SHA: <branch>@<sha>
Working branch: <branch>
Task IDs: <ids>
Dependencies: <merged packages>
Allowed paths: <paths>
Forbidden/shared paths: <paths>
Acceptance checks: <commands and criteria>
Credentials: mock-only | approved env-var names

Read AGENTS.md and CLAUDE.md. Implement only this package. Open a draft PR early,
push bounded checkpoints, and leave a complete handoff if blocked. Never include secrets.
```

## Failure and reassignment

- A stalled agent must push its latest safe checkpoint and describe the blocker.
- Do not assign two agents to the same branch.
- Reassignment uses a new branch from the last reviewed checkpoint unless the prior PR is cleanly resumable.
- After two failed attempts, mark the issue `needs-decision` and stop automatic retries.
- Contract disagreements always escalate to an ADR; Fable never resolves them by majority vote.

## Credential policy

Fable may transmit environment-variable names and setup instructions, never secret values. Live provider tests are separate, explicitly labeled work. GitHub, Railway, and Supabase secret stores are the only intended delivery mechanisms.
