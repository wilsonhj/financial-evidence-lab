# Financial Evidence Lab: open-backlog resolution specification

Date: 2026-09-09 (America/Los_Angeles)

Review baseline: `75fad38de5745ed879d3b36227c2ffe006048456`

Tracking umbrella: [#188](https://github.com/wilsonhj/financial-evidence-lab/issues/188)

This is a review specification subordinate to
`specs/001-financial-evidence-lab/spec.md` and its implementation plan. The
parent governs on conflict. It does not supersede an ADR, change product scope,
authorize paid evaluations, or duplicate the canonical task ledger. The
[resolution plan](../superpowers/plans/2026-09-09-backlog-resolution.md)
defines execution order; the issue audit below defines coverage and closure.

## Outcome and scope

Every issue open at the review snapshot must have a verified disposition,
bounded remaining work, an owner/workstream, dependencies, acceptance evidence,
and a closure condition. Review and repair all open PRs, then merge only
reviewed revisions with current required checks passing. The four initial PRs
are #232, #241, #250 and #251. GitHub had 39 open issues, including #249;
the user-provided 43-issue list was an older inventory.

This session implements PR review fixes and the resolution documents. The
remaining product backlog is planned, not asserted implemented. A merged
implementation and a passed live milestone gate are different deliverables.
Neither an open tracker nor an unchecked canonical task is sufficient evidence
that code must be written again.

## Required behavior

1. **Admission and metering:** equivalent organization UUID spellings consume
   the same rate bucket. Concurrent query/rerun admission observes pending
   reservations. Terminal state and actual usage commit atomically. Failed
   persistence retains the reservation. A rerun charges its requesting member.
2. **Claims:** consume locally validated provider JSON; citation IDs must belong
   to selected context. Numeric value, unit, period and scale are independent
   assertions checked against evidence. A matching tuple does not prove the
   accompanying prose. The lexical mock may fully support only whole-evidence
   identity after whitespace normalization; transformed prose is qualified or
   unsupported. A live semantic verifier needs separate measured acceptance.
3. **Contract integration:** #232 releases 0.5.0; #241 follows at 0.6.0. Preserve
   both typed generation abstention/usage and budget threading in the shared
   pipeline. Keep OpenAPI, package version, exported constant, generated client,
   fixtures and tests consistent. Record the already accepted claims ADR as
   ADR-0015, leaving the migration ledger ADR-0014 intact.
4. **Diagnostics:** optional API Sentry initialization disables frame locals and
   request bodies as well as default PII. This is a bounded collection policy,
   not a claim that arbitrary exception text can never contain sensitive data.
5. **Runtime:** preserve #250's Node 24.20.0 pins and pnpm version. Any newly
   discovered dependency advisory remediation gets its own issue and PR with
   minimal patched versions, frozen lockfile and fresh security evidence.
6. **Backlog accuracy:** preserve completed migration, worker, reader and gate
   implementations. Plan only verified residuals; associate acceptance-only
   trackers with the actual owning issue. Never close a milestone merely
   because all its implementation PRs merged.

## Unchanged release gates

The source of truth remains parent specification sections 19.6 and 26. These
numbers are acceptance constraints, not knobs for making mock results pass:

| Measure | Required result |
|---|---:|
| Temporal validity | 100% |
| Numeric value/unit/period/sign/scale accuracy | >=99.0% |
| Citation entailment precision | >=95.0% |
| Citation completeness | >=92.0% |
| Retrieval Recall@10 | >=90.0% |
| Guidance extraction F1 | >=90.0% |
| KPI/revenue-driver extraction F1 | >=88.0% |
| Contradiction-detection recall | >=90.0% |
| Unsupported-answer abstention precision | >=95.0% |
| 80% forecast interval empirical coverage | 75%–85% |

Advanced forecasts stay non-default unless they beat seasonal-naive median
MAE on supported one-to-four-quarter horizons. The M2 smoke set contains
50–100 questions (the existing seed has 65); final release requires a frozen,
dual-adjudicated set of at least 300. The M1 corpus requires at least 20
benchmark issuers and eight years of available filings. The 5,000-node model
recalculation p95 target is below 500 ms on the parent's reference profile.

Extraction review thresholds remain record confidence below 0.85 or any field
below 0.80; failed validation and conflicts require review. Monetary facts,
guidance and model assumptions never auto-approve regardless of confidence.

## Decisions and external dependencies

- OpenAI remains the accepted ADR-0002 baseline. Proposed ADR-0012 does not
  authorize a substitution. #195 resolves the provider interface and disputed
  directive; use measured evidence before accepting any substitution.
- #177 owns credential provisioning and benchmark execution through approved
  secret flows. Do not copy credentials into this plan, GitHub or logs. Provider
  and model availability must be checked against primary documentation at
  implementation time; old issue model names are not an operational pin.
- #201's current mock Recall@10 shortfall is a measured failure. Keep it visible
  while fixing corpus/index/query behavior or introducing a validated live
  configuration. A fixture regression check may have its own explicit expected
  result, but it cannot certify the release gate.
- Unit identity (#153), guidance ordering (#154), model/forecast storage
  (#197/#219/#64/#66), and provider substitution require their scoped accepted
  ADR/contract changes before dependent implementation. Do not smuggle those
  decisions into a documentation reconciliation.
- #190 and #108 need environment verification. A role migration or fixture
  browser run alone cannot establish deployed least privilege or a hosted
  worker-to-reader path.

## Review acceptance

For each PR retain reviewed base/head SHAs, concrete findings, regression
evidence, final validation links and merge SHA. Existing green checks on an
earlier head do not certify a fix. A skipped PostgreSQL suite is not database
evidence. A security failure blocks merge even when unrelated tests pass.

For each issue retain an immutable code/evaluation artifact link and explain
which acceptance criteria it proves. Close only after all remaining criteria
pass; transfer a residual only to an explicitly linked owner accepted by the
integration lead. Canonical task checkboxes remain lead-owned and are not
changed by this review.

## Complete issue audit

[The issue-by-issue audit](2026-09-09-open-issue-audit.md) covers all 39 initial
issues and the newly discovered #252 security blocker: 40 distinct session
issues. It includes exact proposed paths, existing shipped work, remaining
acceptance cases, dependencies and closure evidence. #249 closed through #250
during review. Re-query GitHub before execution; dated snapshots are evidence,
not a live queue.
