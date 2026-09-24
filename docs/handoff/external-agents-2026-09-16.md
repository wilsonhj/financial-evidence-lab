# Financial Evidence Lab: external-agent task bundle

Prepared 2026-09-16. Repository: https://github.com/wilsonhj/financial-evidence-lab.
Research baseline: `255145435a88d133e5095057a3debeef08db0724` (`main`).
Independent PR review target: #320, `e9ddc0bfe1450fc5de40987bf0fbe3f1b656e14f`.
PR #320 has since merged as `69ed8b9`; the PR head above was independently reviewed.
Card 08 is optional historical revalidation, not an open-PR merge assignment.
Current implementation checkpoint: explicit-key OpenAI adapters merged in
#328/#329 and the offline cipher in #331. Read `docs/handoff/STATUS.md`; statements
about absent adapters at the research baseline are historical. Runtime/live proof
remains outstanding; external agents must not redispatch these merged packages.

This is a standalone dispatch brief for bounded external research and review.
Cards 01–08 are ready for read-only work. Cards 09–10 are **proposed implementation
packages, not permission to start coding**: the integration lead must first create
or select one issue, register exclusive paths and branch, settle their interface
decisions, and explicitly dispatch them. Existing lead/provider/auth/load/reader
owners retain their work. These cards do not replace the canonical task ledger.
Brief card IDs 01–10 are local to this document and are distinct from the completion
plan's role IDs 01–50; matching numbers do not imply matching owners or assignments.

## Rules applying to every card

1. Read `AGENTS.md`, `.specify/memory/constitution.md`, the parent specification,
   plan and task ledger under `specs/001-financial-evidence-lab/`, and
   `docs/handoff/{README.md,workstreams.yaml}`. Read nested instructions where present.
   Accepted ADRs govern; issue proposals and old comments do not override them.
2. Use your own checkout/worktree, one issue and one branch per worktree. For
   read-only reviews, a detached checkout of the specified SHA is sufficient.
   Verify `git rev-parse HEAD` and `git status --short` before and after work.
   Do not switch, reset, clean, or format another agent's checkout.
3. Return findings directly to the integration lead as a report or attachment.
   **Do not post GitHub comments/reviews, send messages to third parties, push,
   open PRs, close issues, merge, deploy, or mark tasks complete.** This narrow
   external assignment overrides the normal handoff instruction to publish PRs.
4. Read-only cards may read tracked source, run offline tests that only generate
   ignored artifacts, and write a report outside the checkout. No tracked-file
   edits, snapshot updates, package upgrades, migrations, live workloads, or
   credential discovery. Never print environment/config secret values.
5. No keys, session tokens, cookies, real customer data or private prompts in
   reports, screenshots, traces, fixtures, tool arguments, commits, or chat.
   Use invented test identities/tokens. Report needed variable **names** only.
6. Public signup serves private, confidential workspaces. Every user's AI usage is
   paid by that user, including embeddings, background work, retries and
   verification. **No owner-funded allowance or owner-key fallback exists.**
   Existing shared bearer configuration is an audit subject, not authorization
   to reuse it. Missing, revoked or depleted user credentials fail before a call.
7. No paid calls or new service commitments. Public official documentation can
   be read for Card 02; SEC fetching requires the lead's approved contact identity
   and coordinated rate budget. Card 03 is offline research only.
8. At most **four agents total** may be active: **three writers/specialists plus
   the integration lead**. Read-only specialists consume those same slots. The
   lead schedules ownership; never interpret “up to 50 agents” as 50 concurrent
   writers or four writers in addition to the lead. Rotate bounded assignments.
9. Shared paths are lead-owned: `.github/**`, `.specify/**`, `specs/**`, root
   configs/locks, `AGENTS.md`, `packages/contracts/**`, `db/migrations/**`,
   `docs/decisions/**`, and handoff ledgers. Proposed implementation cards must
   not change these unless separately registered with the required governance.

### Setup and evidence format

Fetch through your normal approved Git access, then use a detached review checkout:

```bash
git fetch origin main
git switch --detach 255145435a88d133e5095057a3debeef08db0724
git rev-parse HEAD
git status --short
```

Do not run `git switch` in a checkout you did not create. Use Python 3.11 with
the repository's locked dependencies and Node/pnpm versions declared by the repo;
do not repair your environment by modifying lockfiles. Commands below assume
that environment is already prepared. If a dependency is missing, report the
missing prerequisite. Database-dependent tests require a **fresh dedicated local
test database**, never an inherited DSN or hosted/shared database.

Every return must contain: card ID, reviewed SHA, files/lines or official URLs,
conclusion, exact command and exit status, passed/failed/skipped counts, reproducible
trigger and impact for each finding, smallest proposed repair, remaining unknowns,
and a declaration of any modifications/network activity. Distinguish source
inspection, simulated execution, real local HTTP, and hosted evidence. A plausible
risk is not a verified defect; put unproven hypotheses in a separate section.

## 01 — Shared-bearer and BYOK boundary audit

**Status:** ready, read-only. **Related:** #292, #195, #191.
**Read scope:** `apps/web/src/**`, `apps/api/app/**`, auth/cost tests,
`packages/providers/**`, Railway config, credential docs. **Write scope:** none.

Trace request identity from browser to Next server to API to provider. Locate all
environment bearer fallbacks, API route/proxy forwarding, tenant membership checks,
cache keys, logging and trace paths. Determine whether two users could execute
under one configured owner identity or consume one owner's provider account.
Separate a local mock-only convenience from a reachable hosted configuration.
Do not probe real users or inspect actual credentials.

```bash
rg -n 'Bearer|Authorization|FEL_.*TOKEN|API_KEY|cookies\(|headers\(' apps/web/src apps/api/app packages/providers
python -m pytest apps/api/tests/test_auth.py apps/api/tests/test_supabase_auth.py -q
```

**Return:** one identity/data-flow diagram, exact fallback entrypoints, a minimal
two-user synthetic reproduction when feasible, and proposed fail-closed boundaries.
Include negative cases for user A/user B, expired token, missing BYOK, logout,
revocation and cached response reuse. Do not implement a credential store.

## 02 — Provider capabilities, licensing and cost evidence

**Status:** ready, read-only. **Related:** #195, #132, #177.
**Read scope:** provider protocols, ADR-0002/0012, benchmark specs, official vendor
documentation/model cards/licences. **Write scope:** none.

ADR-0002 accepts OpenAI generation and text-embedding-3 at at most 512 dimensions.
ADR-0012 is Proposed and gates substitution only. No live provider implementation
exists at the research baseline. Do not promote the old issue string
`claude-opus-4-8` to a verified or approved model.

```bash
git ls-tree -r --name-only HEAD packages/providers
sed -n '1,180p' packages/providers/fel_providers/interfaces.py
```

**Return:** timestamped source-linked matrix for the OpenAI proof-of-concept baseline
and the user's research candidates DeepSeek V4.1 Flash, Qwen3.8 and Kimi K3:
first verify whether these exact names identify available models; mark unknown
names unresolved instead of silently replacing them. Include available exact
model/version IDs, schema-constrained
output/refusal behavior, usage fields, embedding dimension support, retry guidance,
licence terms and current published pricing. Identify terms requiring review rather
than interpreting legal permission. Estimate a 65-question three-run experiment
using explicitly stated token/embedding assumptions; no live calls. Flag prompt,
retention, data residency and BYOK implications. Recommend the smallest adapter
scope without making a provider-substitution decision.

## 03 — SEC fixture witness gap map

**Status:** ready, offline read-only. **Related:** #81, #56, #177.
**Read scope:** `evals/datasets/sec-fixtures/**`, cohort, corpus-QA harness and
ingestion parser tests. **Write scope:** none. **No SEC network requests.**

The 60 historical fixture records were recovered, not freshly verified. Seven
historical labels are not seven proven feature types. Current full acceptance
intentionally refuses; eight byte-verified types remain required. T0112 belongs
to #177, not a new #56 implementation.

```bash
python -m unittest discover -s evals/datasets/sec-fixtures/tests -p 'test_*.py' -v
python evals/datasets/sec-fixtures/validate.py --structural-only
python evals/datasets/sec-fixtures/validate.py
```

**Return:** missing-witness table covering source bytes/hash, feature location,
fetch receipt, amendment-original relation and excerpt provenance; design for an
additive supplemental manifest preserving canonical cohort consumers; proposed
fetched-data discovery queries for 3–6 supplemental issuers. Explain the expected
nonzero full-validation exit. Do not fabricate URLs, features or success. The
future fetching plan must share one ≤2 requests/sec SEC budget across all agents.

## 04 — Load acceptance methodology audit

**Status:** ready, read-only. **Related:** #61.
**Read scope:** `apps/api/benchmarks/**`, extraction review query-budget tests,
performance docs and committed results. **Write scope:** none.

Prior batch repair reduced SQL from 829 to 37, but latest recorded bulk p95 was
about 1,502 ms against 1,000 ms. Host contention evidence is not a passing result.
Audit workload fidelity, 25-user overlap, sample counts, clock boundaries, percentile
calculation, error accounting, SQL counts, and target provenance. Do not tune the
threshold, relax durability, select a passing subset, or launch a new load run.

```bash
python -m pytest apps/api/tests/test_extraction_load_report.py -q
rg -n 'p95|percentile|concurr|overlap|sample|WAL|timeout' apps/api/benchmarks
```

**Return:** acceptance checklist separating runner validity from target performance;
recompute reported percentiles from committed raw samples where available; list the
minimum dedicated-target configuration and monitoring required for an interpretable
rerun. Any benchmark repair is a proposed patch, not an edit in this assignment.

## 05 — Reader and review accessibility audit

**Status:** ready, read-only. **Related:** #108, #61, downstream #65.
**Read scope:** reader/extraction UI components, associated tests and browser tests.
**Write scope:** none. Use committed fixtures; no hosted login or provider calls.

```bash
pnpm --filter @fel/web test src/components/reader-a11y.test.tsx
rg -n 'aria-|tabIndex|role=|onKeyDown|focus' apps/web/src/components apps/web/src/app
```

Trace keyboard-only citation navigation, review selection, modal focus return,
status/error announcements, disabled actions, loading, empty and forbidden states.
Use an existing local fixture browser setup if available; do not invent live
evidence or replace fixture data. Check visible focus and zoom/reflow manually
where a browser is available.

**Return:** scenario matrix with observed versus untested results, reproducible
keyboard steps and relevant WCAG criteria for concrete failures. Keep UI design
preferences distinct from accessibility defects. Do not claim the unit test alone
proves full browser accessibility.

## 06 — Confidence calibration design review

**Status:** ready, read-only. **Related:** #62, #132.
**Read scope:** `specs/003-agentic-extraction/**`, #62 scope, extraction confidence
implementation/tests, eval data and parent thresholds. **Write scope:** none.

```bash
python -m pytest workers/tests/extraction/test_confidence_and_priority.py -q
rg -n 'calibr|confidence|M3-30[0-4]|T0306|T0307|T0310' specs workers/src evals
```

**Return:** concrete data split and leakage-prevention proposal, labels and human
adjudication needs, abstention/unsupported-evidence treatment, metric/threshold
mapping, immutable report provenance and failure criteria. Identify which work is
offline and which requires real provider smoke. M3-304 cannot be declared complete
by mock tests. OpenAI baseline need not wait for proposed substitution ADR-0012.
Do not invent favourable calibration measurements or count model self-grading as
independent human ground truth.

## 07 — Production auth negative-case matrix

**Status:** ready, read-only. **Related:** #292, #108.
**Read scope:** auth middleware/config, membership provisioning, API auth tests,
web session forwarding and ADR-0025. **Write scope:** none.

```bash
python -m pytest apps/api/tests/test_auth.py apps/api/tests/test_supabase_auth.py -q
rg -n 'issuer|audience|jwks|exp|membership|mock' apps/api/app/auth* apps/api/tests/test_supabase_auth.py
```

**Return:** test matrix for missing/malformed bearer, signature/issuer/audience/
expiry rejection, JWKS rotation/unavailability, member removal, org isolation,
unauthorized workspace, mock token on production config, and browser session
expiry/logout. Map each case to an existing test or a precise missing test.
Database-dependent membership cases may be marked unrun if no isolated DB exists;
no production user creation or authenticated hosted probing.

## 08 — Optional historical revalidation of merged PR #320

**Status:** ready, read-only historical review; PR merged as `69ed8b9` after
independent review. **Original reviewed target:** exact SHA
`e9ddc0bfe1450fc5de40987bf0fbe3f1b656e14f`, not the older reviewed `0ba3068`.
**Read scope:** PR diff, controller, reader browser workflow, tests and README.
**Write scope:** none. Do not approve/post/merge or describe the PR as open.

In your own checkout, obtain `refs/pull/320/head`, resolve it and compare with the
pinned SHA. If it changed, report the mismatch and request a new review pin from
the lead; do not silently substitute a different head. Alternatively inspect the
merged patch at `69ed8b9` and clearly label that commit as your review target.

```bash
git fetch origin refs/pull/320/head
git rev-parse FETCH_HEAD
git diff 255145435a88d133e5095057a3debeef08db0724...e9ddc0bfe1450fc5de40987bf0fbe3f1b656e14f --stat
PYTHONPATH=. python -m pytest evals/tests/test_reader_prod_smoke.py -q
```

Run tests only after checking out the pinned PR SHA in your own review checkout.
Trace automatic recovery beyond the browser's 120-second outage budget, explicit
start recovery, repeated stop, abandoned stop, signal cleanup, atomic control file
updates, child failure and remote recovery. Distinguish mocked clock/subprocess
tests from real HTTP or hosted verification.

**Return:** severity-ranked actionable findings with line references, or explicit
no-findings conclusion; tested head, commands, skips and limits. Prior approval of
an earlier SHA and green CI do not substitute for reviewing the rebased diff.

## 09 — Proposed SEC witness validator implementation

**Status:** NOT DISPATCHABLE until lead registration. **Related:** #81.
**Candidate ownership:** `evals/datasets/sec-fixtures/validate.py` and its dedicated
tests only. Another agent must not own these files simultaneously. Dataset fetching
and manifest edits remain a separate lead-assigned package.
**Forbidden:** all other tracked paths, cohort edits, network fetching, provider
code, root configuration and shared paths.

After Card 03 and lead approval of the witness format, extend full validation to
verify hashes against actual supplied bytes, tag-specific witnesses, original/
amendment provenance, excerpts and ≥8 distinct features across canonical plus
clearly supplemental entries. Keep structural-only mode explicitly non-acceptance.
Missing or forged evidence must fail closed. Do not accept historical assertions
or nearby arbitrary cache files as proof.

**Acceptance:** offline tests cover valid witnessed fixtures, altered bytes,
unproven tags, missing originals, supplemental/cohort separation, missing files,
malformed receipt metadata and fewer-than-eight features. Run the Card 03 unittest
command. Return patch and evidence to lead; no push/PR/merge under this brief.

## 10 — Proposed immutable live-evaluation report validator

**Status:** NOT DISPATCHABLE until lead registration and report-interface freeze.
**Related:** #132, #201, #177. **Candidate ownership:** one new dedicated validator
module under `packages/retrieval-evals/fel_retrieval_evals/` and its matching test
file. Exact filenames are assigned in the dispatch record. Existing harness,
metrics module, CI workflow and dataset writers remain lead-owned.
**Forbidden:** all other tracked paths, threshold changes, provider calls,
credentials, financial calculations, migrations and shared paths.

Validate the lead-approved report format: exact revision and corpus/question/
answer-key/prompt/schema/config hashes; resolved corpus/index identity; all 65
questions and all five supported metrics; repeated-run protocol fixed before
execution; exact model identity, usage and cost provenance. Reject mock reports as
live proof, incomplete outcomes, missing supports and post-hoc pass criteria.
Consume existing frozen thresholds rather than copying a second threshold table.

**Acceptance:** tests for valid evidence, missing/duplicate questions, invalid
hashes, provider identity mismatch, missing metrics, zero support, mock/live
confusion and failed gate propagation. Run focused tests plus existing
`packages/retrieval-evals/tests/test_metrics.py`. Schema/CLI/API additions require
lead approval before implementation; return patch and tests directly to lead.

## Settled product decisions and remaining lead gates

The following user decisions govern all cards, even where older repository prose
still describes a project-funded provider credential:

- Public signup; every workspace is private and confidential with per-user identity
  and tenant isolation. A server-configured owner bearer cannot impersonate users.
- OpenAI is the proof-of-concept baseline. Research the named alternatives above
  for cost/capability; no substitution is approved by a research card.
- OpenRouter PKCE is the first credential onboarding flow. Store its resulting
  user-bound credential encrypted server-side; direct OpenAI/Anthropic BYOK is a
  follow-up. ADR-0026 selects the existing locked Fernet/MultiFernet library with
  an explicit deployment keyring outside the DB. This is symmetric authenticated
  encryption, not envelope encryption; the offline primitive does not implement
  authorization, storage, revocation or hosted acceptance.
  Never place keys in public assets, `NEXT_PUBLIC_*`, queue payloads or logs.
  Queued work carries a credential reference only; workers revalidate ownership
  and revocation before calls. Arbitrary provider base URLs are not supported.
- Users fund **all** AI, including embedding/index work, retries, background jobs
  and verification. Earlier proposed owner-funded/admin allowances are superseded.
  Missing/revoked/depleted credentials fail before calls; no fallback exists.
- Provider routing must use a privacy allowlist with no-training and approved
  retention terms. Unknown privacy properties fail closed. Cost-driven routing
  may not silently weaken privacy or change pinned provenance.
- Downstream financial models use fiscal scalars plus explicit derived bridges;
  scenarios override forward drivers only; intervals derive from historical errors.
  These are context for calibration/review, not permission to implement #64–#68.

The lead retains interface/schema registration, credential lifetime/revocation
mechanics, exact approved model/provider routes, benchmark repetition protocol,
dedicated target selection, user-approved spend caps, SEC contact identity,
adjudicator staffing and final acceptance. Return unresolved implementation details
instead of inventing them. Never request secret values in chat or use an owner's
credential to bypass a missing dependency. These gates do not block read-only cards.

Completion means evidence delivered to the lead. It does not mean an issue closed,
an external review posted, a code change merged or a hosted gate passed.
