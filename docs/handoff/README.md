# Implementation handoff

This directory is the restart point for all implementation agents. Fable must be able to reconstruct the queue solely from GitHub and `workstreams.yaml`; conversation history is optional context.

## Current state

- Trunk is `a4bb356` (PR #174). This block was last reconciled 2026-08-30. The
  revision it replaces on trunk was pinned to `ace7b83` by PR #168 @ `64eb571`
  — `ace7b83` is PR #165's merge commit, not #168's — and was wrong
  within hours of the merges that followed it, so re-resolve against
  `origin/main` rather than trusting this line.
- Specification (v1.2) and architecture (ADR-0002) are approved. Contracts are
  frozen at OpenAPI `v0.4.0` with migrations through `0005`.
- `main` is the only implementation base; `integration/m0` is retired. Every
  push and PR is CI-gated.
- **The project is Apache-2.0, not MIT.** PR #166 @ `5394c64` relicensed it and
  added a `NOTICE` file; `LICENSE` is byte-identical to the canonical
  Apache-2.0 text. Contributions carry the patent grant and the NOTICE
  obligation.
- M0, M1 and M2 are complete. The M3 core landed as `M3-EXTRACTION-CORE` (#60,
  PR #145 @ `61058e4`), with follow-up fixes in #156, #160, #170 (#169),
  #162 (#155, the orphaned normalize modules — now wired in), and #174 (#171,
  segment-sum over-suppression).
- `EVALS-REPORT-RENDER` (#151) merged as PR #164 @ `a23514e`; its entry read
  `ready` ever since that 2026-08-11 merge — this reconciliation is what
  flips it — so an agent reading the queue in that window would have
  re-taken finished work. `M4-MODEL-CALC` (#63) now reads
  `status: ready`. Open PRs are #172 (this ledger), #173 (004-mvp-completion),
  and #175 (ADR-0011 ratification). Re-run `gh pr list --state open`. Do not
  infer dispatchability from a stale `ready` — confirm the issue is open on
  GitHub first.
- `M4-MODEL-CALC` (#63) is `ready`: its only dependency is merged,
  `packages/calculation-engine/**` overlaps nothing in flight, and credentials
  stay mock-only — this reconciliation **adds** the key. `M3-REVIEW` (#61)
  stays `status: blocked` on three holds: ratification of ADR-0011 (PR #175,
  Accepted on that PR), migration 0006 via #157 before SSE exposure, and
  unimplemented #146 Option 1 (terminal runs final, ruled 2026-08-29) as a
  producer gate. `M3-CONFIDENCE-GATE` (#62) is genuinely not unblocked — it
  `depends_on: [M3-REVIEW]`.
- Integration lead ruled ADR-0011 over ADR-0009; ratification is PR #175
  (Accepted on that PR). Do not expose SSE until migration 0006 lands via
  #157. #146 Option 1 (terminal runs final) was ruled 2026-08-29 but is not
  yet implemented. ADR-0010 (PR #165) remains **Proposed** and ratifies nothing.
- Provider credentials are intentionally unavailable. Work stays mock-first;
  hosted smoke (#108) credentials are not provisioned.
- Trunk health: `main` @ `a4bb356` is **green** — all five GitHub Actions check
  runs pass. #171 is closed (fixed by #174). The `audit-bulk` red at `ace7b83`
  (`js-yaml` GHSA-5p4m-2wfm-xmqj, `nanoid` GHSA-2v37-7h3g-55p8) was fixed by
  PR #167 @ `7eba341`, so a red branch is now your own doing. Ignore the
  `cursor`, `claude`, `supabase` and `vercel` check *suites*: they sit
  permanently `queued` and never resolve, which makes green trunk look pending.

Read `STATUS.md` for live state and `workstreams.yaml` for the authoritative dependency graph. External agents doing parallel preparation work start from `EXTERNAL_AGENT_BRIEF.md`.

## Source of truth

1. GitHub merged commits, issues, and PRs
2. `workstreams.yaml`
3. `STATUS.md`
4. Spec Kit artifacts under `specs/001-financial-evidence-lab/`

Only the integration lead changes bundle status to `merged`, checks tasks, changes dependencies, or updates shared contracts.

## Dispatch checklist

A package is ready only when:

- every `depends_on` package is `merged`;
- its base branch contains the dependency commits;
- no active package overlaps its allowed paths;
- fixture and schema versions match;
- any credential requirement has been explicitly fulfilled; and
- an issue and isolated branch/worktree exist.

Cap concurrency at four packages at all times. Prefer PRs below roughly 600 changed lines and split work that cannot be reviewed independently.

## Emergency resume

1. Fetch `main` and inspect `STATUS.md`.
2. Reconcile `workstreams.yaml` against open GitHub issues and PRs.
3. Treat pushed PR commits as authoritative over uncommitted agent work.
4. Reassign only packages with no active heartbeat or after explicitly closing the previous attempt.
5. Resume the lowest-numbered ready gate; do not bypass milestone exit criteria.
