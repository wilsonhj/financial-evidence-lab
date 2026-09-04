# ADR-0013: Retrospectively authorize the PR #206 canonical task-ledger reconciliation

Status: Accepted
Date: 2026-09-03
Accepted: 2026-09-03 by the integration lead through merge of PR #206
Scope: commit `79799858d4760bcc2f70efd28ea9980c94a4577f` and only its edit to
`specs/001-financial-evidence-lab/tasks.md`

## Context

`specs/001-financial-evidence-lab/tasks.md` is the sole canonical task ledger and
is under the shared `specs/**` path. AGENTS.md requires an ADR, the
`contract-change` label, and integration-lead review for such a change.

PR #206 was nevertheless merged after reconciling the ledger to work already
present on main. It checked sixteen tasks whose owning packages and acceptance
work had already merged: `T0201`–`T0210`, `T0214a`, and `T0301`–`T0305`. It did
not claim unfinished work: `T0112` and `T0215` remained unchecked, with the
missing live-ingest and performance evidence recorded on their lines. The merge
commit message records the measured invariant: no checked task had an unmerged
owner, and the only unchecked tasks with merged owners were those two documented
exceptions.

The integration lead's merge is durable evidence of review and acceptance, but
the missing contemporaneous ADR left the shared-path authorization incomplete.
This retrospective record closes that narrow governance gap; it does not
reinterpret task completion or authorize new specification changes.

## Decision

The integration lead retrospectively authorizes exactly the canonical-ledger
reconciliation merged by PR #206 at commit
`79799858d4760bcc2f70efd28ea9980c94a4577f`.

This one-time correction is valid because it:

1. aligned stale checkboxes with already-merged package outcomes rather than
   changing product scope, requirements, architecture, or acceptance thresholds;
2. preserved unchecked state where acceptance evidence was absent;
3. documented each exceptional unchecked task in the canonical ledger itself;
4. was reviewed and merged by the integration lead; and
5. changed only the canonical ledger file.

No other commit, file, task-state edit, or specification correction is covered.

## Consequences

- PR #206's ledger edit has the required durable ADR authorization.
- The reconciled checkbox state remains a record of merged evidence, not a
  substitute for each task's acceptance standard.
- Future edits anywhere under `specs/**` still require their own applicable ADR,
  `contract-change` label, and integration-lead review under AGENTS.md.
- This ADR creates no standing documentation exception, no blanket
  reconciliation authority, and no broad `specs/**` bypass.

## Alternatives rejected

- **Treat the integration-lead merge alone as sufficient.** Rejected because the
  repository explicitly requires a durable ADR in addition to review.
- **Authorize future ledger reconciliations generally.** Rejected as over-broad;
  later changes may alter scope or assert completion without equivalent evidence.
- **Revert the accurate reconciliation.** Rejected because that would knowingly
  restore stale task state while adding no governance protection.

## Verification

The authorization remains valid only if:

1. `git show --name-only 79799858d4760bcc2f70efd28ea9980c94a4577f`
   shows the canonical task ledger as the sole changed file;
2. the commit changes the sixteen named delivered tasks to checked;
3. `T0112` and `T0215` remain unchecked with reasons; and
4. no reader applies this ADR to any later or different `specs/**` change.