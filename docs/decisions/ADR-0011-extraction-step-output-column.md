# ADR-0011: Add `extraction_run_steps.output` so the checkpoint stops riding on the event payload

Status: Accepted
Implemented: 2026-09-02. Migration `db/migrations/0006_extraction_step_output.sql`
landed on branch `claude/repo-analysis-improvements-m25v4u`, and contract release
**0.5.0** answers the open "Contract-version question" below as a **minor** bump,
not a major one. The reasoning is recorded in `docs/handoff/CONTRACTS.md` under
the v0.5.0 entry: `ExtractionEvent.payload` keeps `additionalProperties: true`,
every schema `$id` is unchanged, and `stage_output` was never a declared
property — so Reading A holds and `1.0.0` is not warranted. `VERSIONING.md` now
states the companion rule that a nullable widening keeping the property
`required` is additive. Decision items 2-7 are therefore no longer open work.
Date: 2026-08-29
Accepted: 2026-08-30 by integration lead on PR #175
Supersedes: ADR-0009 (`docs/decisions/ADR-0009-checkpoint-payload-in-event-stream.md`,
Status: Proposed, never ratified; historical — this PR sets it to `Superseded by
ADR-0011`) — ADR-0009's proposed amendment is withdrawn unexecuted.
Occasioned by: issue #157 (`contract-change`, `agent-task`, open), filed as the
follow-up ADR-0009 names in its own "Alternatives rejected".
Blocks: #61 SSE until the *implementing* PR for migration 0006 lands. Non-SSE
#61 work still waits on unimplemented #146 Option 1 (terminal runs final), which
is a separate ruling.

All file:line references verified against this branch's base, `origin/main` @
`a4bb356`. Where a reference could not be verified, the text says so. The one
deliberate exception is every `ADR-0009:N` citation below, which is a
**post-merge** line number: this PR inserts a `Superseded:` line at
`ADR-0009:7`, shifting every line at or below it by one, so citing the base
would leave all nine ranges off by one the moment this lands. See "Notes" on
citation drift — an ADR that moves its own citation target has to say which side
of the move it is citing.

## Context

**ADR-0009 already concedes this decision on the merits.** Its "Alternatives
rejected" section, verbatim (`ADR-0009:135-137`):

> **Add a `steps.output` column.** The correct fix, and the one that would restore
> the original guarantee outright. It is a change to frozen migration `0004`, so it
> needs its own `contract-change` issue and ADR. Worth doing; out of scope for #60.

That rejection is scope-based, not merit-based, and the scope has closed. PR #145
(`feat(m3): M3-EXTRACTION-CORE ontology + worker FSM (#60)`) merged to `main` at
`2026-07-30T17:50:58Z` as merge commit `61058e4`, and issue #60 closed one second
later (`gh pr view 145 -R wilsonhj/financial-evidence-lab`; `gh issue view 60`).
"Out of scope for #60" has no remaining referent. Issue #157 is the
`contract-change` issue ADR-0009 asks for; this is the ADR.

**Nothing has been amended yet.** At the time of this decision ADR-0009 was
`Status: Proposed` (historical; now `Superseded by ADR-0011`) and stated plainly
that it "proposes the change and does not make it"
(`ADR-0009:200-201`). All six guarantee statements are byte-unchanged at
`a4bb356` — each verified individually:

- `specs/003-agentic-extraction/data-model.md:23`
- `specs/003-agentic-extraction/contracts/extraction-api.yaml:180`
- `specs/003-agentic-extraction/spec.md:180`
- `packages/contracts/openapi/openapi.yaml:2012`
- `packages/contracts/schemas/extraction-event.schema.json:36`
- `packages/contracts/src/generated/api.ts:1070` — the **shipped generated
  client**, already in consumers' hands.

So there is no re-amendment to pay for. The choice is not "amend, then unamend";
it is "amend once, downward, in a published client" versus "do not amend, and add
one column."

**The asymmetry, plainly.** Under ADR-0009, the sentence at `api.ts:1070` is
rewritten: a privacy guarantee in a generated client that has already shipped is
weakened, and the weakening reaches consumers as a JSDoc diff no schema
comparison flags. Under this ADR, that sentence and its five siblings are not
touched at all — they simply become true. The engineering price of the second
route is one nullable column in a new forward migration, a straight-line change
to one INSERT and one SELECT, and the **deletion** of the redaction exemption.

**Why the coupling exists.** `extraction_run_steps` has no `output` column
(`db/migrations/0004_extraction_core.sql:143-171`; it has `output_hash` at
`0004:154-156`, but nothing that holds the hashed value). The only durable
carrier is therefore the event payload — `workflow.py:528-534` writes
`"stage_output": serialize_stage_output(output)` under the comment "Frozen 0004
has no steps.output column; persist resume payload here", and
`persist.py:701-729` (`_load_stage_output`) scans `extraction_run_events` to
hydrate it back. `spec.md:61` requires that "a crash after any completed step
resumes from the next incomplete step without duplicating proposals or model
calls already committed." That is the bind ADR-0009 documents, and it is real.

**The schema was written expecting this column.** `0004`'s own immutability guard
carries the comment `-- Steps may advance status/output within an open run.`
(`0004:492`) — naming an `output` the table does not have — and its identity-pin
list (`0004:493-501`) covers only `id`, `org_id`, `run_id`, `step_name`,
`attempt`, `input_hash`, `workflow_version`, `schema_version` and
`prompt_version`, leaving `output_hash` mutable within an open run. The guard
needs no change to accept the column.

**Constitutional dimension.** The metadata-only sentence is a security and
privacy guarantee, not a convenience note. Constitution principle IV
(`.specify/memory/constitution.md:24-25`) makes "tenant isolation, least-privilege
access, immutable audit events, secret protection" non-negotiable. The
least-privilege limb is the one engaged: an operator or consumer granted the
event stream on the strength of a "metadata-only" label receives the full
evidence corpus, so any grant made on that basis is not least-privilege — the
grant was sized against the label, not the contents. Principle I's evidence
integrity is engaged through the hash coupling below: the same strings are
proposal identity inputs, which is why they cannot be redacted in place.

**Two limbs that are NOT engaged, and this ADR does not claim they are.**

- *Tenant isolation is intact.* `extraction_run_events` carries the same
  org-scoped RLS as every other extraction table (`0004:692-695`) with only
  `GRANT SELECT, INSERT ... TO fel_app` (`0004:661`). There is no cross-tenant
  leak, so principle I's "cross-tenant evidence leak is a release blocker" is not
  triggered.
- *Secret protection is intact.* Prompts, provider messages and credentials are
  never inside `stage_output` — they live on the provider call, and `model_step`
  is a sibling key that is still redacted (`events.py:102-108`). `redact_log_payload`
  (`events.py:129`) has no exemption and takes no parameter that could grant one,
  so log lines never carry the text.

The defect is a false published guarantee, not a live confidentiality incident.
Exposure today is bounded to public SEC filing text plus model-derived numbers
over it: the corpus producers are EDGAR only, and `grep -rn extraction apps/api
--include='*.py'` returns one docstring (`apps/api/app/main.py:5`) and one
unrelated cost test — no extraction API surface exists yet at all. This ADR is a
contract-honesty and future-proofing decision made while it is still cheap.

**Hash coupling (why in-place redaction is not available).** Verified at
`a4bb356`, with corrected line numbers — see "Notes" on ADR-0009's citation
drift. `hash_json(clean)` produces `raw_hash` (`validate/pipeline.py:187`), which
becomes `raw_payload_hash` (`:196`) and feeds `proposal_id_for` (`:208-209`);
`stage_input_hash` covers the same payloads as stage input
(`workflow.py:477-482`); and `_restore_output` re-checks `sha256_hex(text)`
against the pinned `text_hash`, raising `IntegrityError` on mismatch
(`workflow.py:612-618`). Truncating or substituting inside that subtree corrupts
a resumed run. This analysis is ADR-0009's, it is correct, and this ADR adopts it
unchanged — it is precisely the reason the fix must be a column and not a smarter
redactor.

## Decision

This document is accepted. Items 2–7 below remain the work of a follow-up
`contract-change` PR against #157 (migration `0006` plus the persist/resume
rewrite). This ratifying PR does not add `0006` or edit `persist.py`.

1. **Supersede ADR-0009.** Its Context, hash-coupling analysis and
   `stage_output`-must-not-be-altered reasoning are retained as the record of why
   the coupling existed; its Decision — amending the six statements to a weaker
   guarantee — is withdrawn unexecuted. The ratifying PR sets ADR-0009's status
   to `Superseded by ADR-0011` (status header only).
2. **Add a nullable `output jsonb` column to `extraction_run_steps` via a new
   forward migration, `db/migrations/0006_extraction_step_output.sql`.** Migration
   `0004` stays byte-identical. `db/migrations/README.md:7-9` is explicit:
   "Migrations are append-only; never edit or delete an applied migration —
   correct forward with a new one." `0005_retrieval_query_guard_role_fix.sql` is
   the precedent — it corrected a `0003` defect in a new file. ADR-0009's phrase
   "a change to frozen migration `0004`" must be read as *a change to the schema
   `0004` defines*, which is permitted; editing the file is not.
3. **Write `output` in the same INSERT as `output_hash`**
   (`persist.py:755-786`), so the hash and the hashed value are one row and one
   write and can never be separately durable.
4. **Read `output` from the step row in `load_succeeded`** (`persist.py:646-699`)
   and delete the event-scan hydration `_load_stage_output` (`persist.py:701-729`).
5. **Drop `stage_output` from the `step_completed` event payload**
   (`workflow.py:532-533`) and **delete the redaction exemption**
   (`events.py:117-126`, and the module docstring's carve-out at `events.py:1-8`).
   `redact_event_payload` collapses to a single mode. This deletion is what
   restores the guarantee.
6. **Amend nothing in `packages/contracts/**` guarantee text.** All six sentences
   stay byte-identical and become true as written. The contract-version pins do
   move — see the next section — and `data-model.md:19` gains `output` in its
   column list, but that is a stale enumeration, not a guarantee.
7. **Leave `model_step` on the event** (hashes and IDs, not source text), and
   leave `redact_log_payload` alone.

## What must change (and what must not)

**Must change**

| Surface | Change |
| --- | --- |
| `db/migrations/0006_extraction_step_output.sql` | new file: `ALTER TABLE extraction_run_steps ADD COLUMN output jsonb;` |
| `db/migrations/tests/0006_*.test.sql` | new harness, per `README.md:65-70` |
| `persist.py:755-786` (`_insert_step_row`) | 19th column in the INSERT |
| `persist.py:646-699` (`load_succeeded`) | add `output` to the SELECT list at `:670-671` |
| `persist.py:701-729` (`_load_stage_output`) | delete |
| `workflow.py:528-534` | drop the `stage_output` key |
| `workflow.py:389-399` (`_commit_stage`) | docstring asserts the event payload is a stage result's ONLY carrier — rewrite, do not delete |
| `events.py:70-126` | delete the exemption; collapse `_redact` to one mode |
| `specs/003-agentic-extraction/data-model.md:19` | add `output` to the column list |
| version pins | `package.json:3`, `openapi.yaml:4` (+ changelog `:5-13`), `src/index.ts:21`, `contracts.test.ts:86,90` |

**Must NOT change**

- `db/migrations/0004_extraction_core.sql` — byte-for-byte identical.
- The six guarantee sentences. They are the point.
- `serialize_stage_output` (`serialize.py:12-34`) **survives**. Output must still
  be JSON-safe for a `jsonb` column; `EvidenceBlock` dataclasses and `datetime`
  still need converting. Only its comments (`serialize.py:1,13`) and call site
  change. Deleting it would be a bug.
- `_restore_output`'s `text_hash` check (`workflow.py:612-618`) — unchanged in
  substance, load-bearing, only its provenance changes.
- `redact_log_payload` (`events.py:129`) and `telemetry.emit`'s use of it.

**No grant, RLS or trigger change is needed** — verified, each individually:

- Grants: `0004:660` is `GRANT SELECT, INSERT, UPDATE ON extraction_run_steps TO
  fel_app` at **table level**, so a new column is covered automatically. Note the
  contrast: `extraction_runs`' UPDATE grant *is* column-scoped (`0004:656-659`),
  so a new column *there* would need an explicit grant. The `0006` header should
  say so, or a future reader will generalise the wrong way.
- RLS: `extraction_run_steps_isolation` (`0004:687-690`) is column-agnostic.
- Trigger: `fel_guard_extraction_run_child` enumerates its pins explicitly
  (`0004:493-501`), so a column added later is unpinned by construction and a
  step may advance it within an open run — which `0004:492` already states in
  those words. `0004:506-509` (forbidding a succeeded step leaving `succeeded`)
  is unaffected.

**Cost and risk, stated honestly**

- *Backfill is impossible, permanently.* Every UPDATE on `extraction_run_steps`
  runs `fel_assert_extraction_run_open` (`0004:510`), which raises for terminal
  runs (`0004:477-479`), and DELETE is rejected unconditionally (`0004:488-489`).
  Rows written before `0006` on runs that have since gone terminal keep
  `output_hash` set and `output NULL` forever. Two consequences: `_is_recoverable`
  (`workflow.py:364-386`) **must be retained** — it degrades from a live
  correctness guard to a legacy-row defence — and an eager
  `CHECK ((output_hash IS NULL) = (output IS NULL))` would fail validation against
  those rows. Add it `NOT VALID` or not at all; the implementing PR must choose
  and say which.
- *The `ADD COLUMN` itself is cheap.* Nullable, no default, catalog-only on
  PostgreSQL 11+, no table rewrite. **Not independently verified here** — no
  database was available in this worktree; the implementing PR should confirm
  against CI's Postgres 17 container.
- *A test-harness hazard must be fixed in the same PR.*
  `ensure_extraction_database` (`workers/tests/extraction/test_postgres_crash_resume.py:109-110`)
  applies migrations only when `to_regclass('public.extraction_runs')` is null.
  Anyone with a pre-existing `<db>_extraction` database would silently run the new
  code against a schema with no `output` column. That marker check must be
  tightened, or the whole crash-resume suite is testing nothing.
- *Regression risk sits on the crash-resume path*, which is exactly where PR
  #145's silent-data-loss bug lived (`persist.py:822-838` records it). The
  mitigation is that this change is mostly a deletion, and that the load-bearing
  new test (resume with the `step_completed` event never written) is stronger
  than anything the current design can express.
- *Three rationales become stale and must be rewritten, not deleted.*
  `commit_succeeded_atomic` (`persist.py:812-855`) loses its justification once
  the step row is self-sufficient — a crash between row and event then costs
  telemetry, not data; whether to keep the transaction as hygiene is a judgement
  call for the implementing PR. `_commit_fence` (`workflow.py:343-361`) stays
  correct, but its rationale paragraph cites `_load_stage_output`'s
  `ORDER BY id DESC LIMIT 1` hazard (`workflow.py:349-352`); with the column plus
  `ON CONFLICT DO NOTHING` against the partial replay index (`0004:173-175`), a
  zombie worker's write loses the race instead of winning it. `_commit_stage`'s
  docstring (`workflow.py:392-399`) is the third and the most directly falsified:
  it states that the `step_completed` event's `stage_output` "is the ONLY carrier
  of a stage's result (0004 has no `steps.output` column)". This decision adds
  exactly the column it says does not exist, so the sentence is false by
  construction the moment `0006` lands.

## Contract-version question (open; must be answered by the implementing PR)

`packages/contracts` is at **0.4.0** (`package.json:3`, `openapi.yaml:4`).
`VERSIONING.md:19-23` classifies "changing the meaning of an existing field" as
breaking; `:25-29` classifies additive change as minor. This ADR does not resolve
it — the same posture ADR-0009 took (`ADR-0009:55-56`) — but it does narrow it,
because the question is a **different** one under this decision.

- **Reading A — additive/minor (0.5.0).** The `payload` description is untouched
  and `payload` remains `type: object, additionalProperties: true`
  (`openapi.yaml:2008-2010`, `extraction-event.schema.json:34-38`). Nothing is
  removed, renamed, retyped or made required; `$id` stays
  `extraction-event/v1`. The only prose that moves is the version changelog in
  `info.description` (`openapi.yaml:5-13`), which a bump always touches.
  Regenerating `api.ts` should therefore leave `:1070` byte-identical.
  **Not run here** — the generator was not executed in this worktree, so the
  implementing PR must confirm the actual diff. Note that issue #157's Reading A
  predicts "a JSDoc-comment-only diff at `:1070`"; that appears to be inherited
  from ADR-0009's framing, where the sentence genuinely is rewritten. Under this
  decision it should not be.
- **Reading B — breaking (major).** `additionalProperties: true` made
  `stage_output` a legal observable field, so its disappearance from the wire is a
  de facto field removal for any consumer that read it. There is no such consumer
  today (no API implements the stream), which is the strongest argument for
  landing this now rather than after #61.

Note the contrast with ADR-0009, which faced the harder version of this question:
there, the description string at `api.ts:1070` is rewritten, so the shipped
client's guarantee text itself changes with no schema diff to signal it. Here the
worst case is the removal of an undeclared key nobody consumes.

Every prior bump moved the middle digit (`0.1.0` → `0.2.0` ADR-0005 → `0.3.0`
ADR-0006 → `0.4.0` ADR-0007), so precedent gives `0.5.0` under either reading;
the reading decides whether `1.0.0` is warranted. **The commit-level provenance
of those four bumps is asserted by issue #157 and was not independently
re-verified for this ADR.**

## Consequences

- **The event stream becomes genuinely metadata-only**, and all six published
  statements become true without any of them being amended. That is the whole
  benefit, and it is the one ADR-0009 says it wants.
- **#61 (M3-REVIEW) must be sequenced after this.** `workstreams.yaml:349-356`
  shows #61 `status: blocked` with `allowed_paths: [apps/web/**, apps/api/**]`.
  The OpenAPI contract already publishes
  `GET /v1/extraction-runs/{runId}/events` as a bearer-authenticated
  `text/event-stream` with `Last-Event-ID` resume
  (`packages/contracts/openapi/openapi.yaml:566-601`), and nothing implements it.
  #61 is the package that would first mount it. If #61 ships first, it exposes a
  browser-reachable stream carrying verbatim filing text under a contract saying
  it carries none, and `apps/web` may build against `payload.stage_output` —
  after which removing the key becomes a real breaking change for a real
  consumer instead of a no-op diff. Add this work to #61's `depends_on`.
  ADR-0009 flags the same trigger from the other side (`ADR-0009:166-168`).
- **A new `workstreams.yaml` entry is required.** `M3-CONTRACT` (#101) is the
  only entry spanning both `db/migrations/**` and `packages/contracts/**` and it
  is `status: merged`; the precedent for a new retroactive entry is
  `DB-GUARD-HARDENING` (#125, created for the `0005` record). The new entry needs
  `db/migrations/**`, `db/migrations/tests/**`, `packages/contracts/**`,
  `specs/003-agentic-extraction/**`, `docs/decisions/**`, plus the
  `workers/src/fel_workers/extraction/**` and `workers/tests/**` paths currently
  held by `M3-EXTRACTION-CORE`. That path overlap needs the integration lead to
  sequence it against #62. **The `workstreams.yaml` line numbers for #101 and
  #125 are asserted by issue #157 and were not independently re-verified; the
  #61 entry above was.**
- **Governance.** `db/migrations/**`, `packages/contracts/**`, `specs/**`,
  `docs/decisions/**` and `docs/handoff/workstreams.yaml` are all integration-lead
  shared paths (`AGENTS.md:29-39`), and changes require an ADR, the
  `contract-change` label and integration-lead review (`AGENTS.md:20,41`;
  `VERSIONING.md:44-51`; `db/migrations/README.md:10-11`). #157 already carries
  both labels.
- **ADR-0009's revisit triggers mostly retire with it.** Its non-public-source
  trigger (`ADR-0009:162-165`) becomes moot — the stream stops carrying source
  text regardless of the corpus. Its redaction-helper trigger
  (`ADR-0009:172-174`) also retires, since there is no exemption left to
  re-merge. Its #61 trigger is what this ADR converts into a sequencing
  requirement.
- **Nothing about the run's durability or fencing weakens.** Checkpoint identity
  `(run_id, step_name, input_hash, workflow_version)` (`workflow.py:477-489`,
  `0004:173-175`), double fencing (`workflow.py:334-340`, `:343-361`), and the
  `text_hash` integrity check are all preserved. This is a change of carrier, not
  of semantics.

## Alternatives rejected

**Keep ADR-0009: amend the six statements and change no code.** This is the
serious alternative, and the case for it is genuine:

- *ADR-0009 is true.* It describes what the code actually does. A specification
  corpus that describes reality is worth more than one that describes an
  aspiration, and amending is the only route that makes the corpus honest
  *immediately*. This ADR's route leaves a false published guarantee standing for
  as long as the implementation takes — and implementations slip. If #157 stalls,
  ADR-0009's route would have been strictly better.
- *The exposure is bounded and is not an incident.* Public EDGAR text only, no
  ingestion path, no consumer of the stream. Weighed against that, a migration
  plus a rewrite of the resume path is a large intervention for a documentation
  defect.
- *The code being deleted was expensive to get right.* The positional exemption
  (`events.py:117-126`) and the atomic commit (`persist.py:812-855`) took two
  review rounds and a review finding (M4) to converge; two earlier key-based
  scopings both corrupted the checkpoint (`ADR-0009:76-87`). Replacing working,
  hard-won code on the crash-resume path carries regression risk that a prose
  amendment does not.
- *Neither route is contract-free.* This ADR still moves the version pins and
  still edits `data-model.md:19`, so "no contract change" would be a false claim
  for it.
- *The risk is asymmetric in the other direction too.* This route rewrites the
  crash-resume path — the exact code where PR #145's silent checkpoint-corruption
  bug lived, and where two earlier key-based scopings already failed
  (`ADR-0009:76-87`). A botched implementation here produces a **correctness
  incident**: a resume that silently loses or mis-attributes an extraction.
  ADR-0009's route produces, at worst, a documentation defect. Measured by
  worst-case severity rather than by which document is true, ADR-0009 is the
  conservative choice, and this ADR is asking to take on execution risk in
  exchange for a guarantee that is currently costing nobody anything.

**Rejected because** the deciding factor is not which document is currently true,
but which end-state is worth having. The amendment's cost lands in an already
shipped generated client and is paid by consumers who cannot see it coming: a
JSDoc-only change to `api.ts:1070` that no schema diff surfaces, weakening a
privacy guarantee they may have provisioned access on. The column's cost lands in
this repository, is paid once by this team, is reversible, and is bounded by the
verified facts above — no grant change, no RLS change, no trigger change, one
nullable column, and mostly deletions. Weakening a published guarantee to match
an implementation, when the implementation can be fixed for this price, inverts
the direction the constitution's principle IV points. The interim-window
objection is real and is answered by sequencing, not by argument: this must land
before #61, and if it cannot, the fallback is to reopen ADR-0009 rather than to
ship #61 over the gap. The execution-risk objection is the strongest one against
this ADR and is not dismissed: it is why the "Verification" section below demands
a crash-resume test with the `step_completed` event never written, and why the
implementing PR must be reviewed as a correctness change on the resume path
rather than as a schema addition. If the integration lead judges that risk
unacceptable while #61 is the immediate priority, ratifying ADR-0009 and
deferring this is a defensible call — it should just be made knowingly, rather
than by leaving the fork open.

**Store stage output in object storage and reference it by key.** Rejected now;
ADR-0009's objection (`ADR-0009:138-141`) is unchanged and this ADR endorses it —
a second durability system on the resume path with a failure mode (event
committed, blob missing) the current transaction boundary cannot cover. Its
stated merit, scaling better than JSONB, survives as a future option if stage
payloads ever outgrow a `jsonb` column; the column does not foreclose it. Note
the objection is *weaker* against the column than against the event, since the
column puts the hash and the hashed value in one row and one write — but "weaker
objection to the thing we are not doing" is not a reason to do it.

**Truncate and re-fetch on resume.** Rejected, and ADR-0009's corrected reasoning
(`ADR-0009:150-158`) survives intact and re-verified: only pinned span text is
re-fetchable — `handler.py:263-305` verifies evidence against canonical
`source_spans` rows, `persist.py:82` and `:337-358` load them, and a re-fetch
path exists in `apps/api/app/reader.py:82,90`. But `stage_output` also carries
`state.classification`, `state.candidates`, `state.raw_proposals` and
`state.normalized` (`workflow.py:629-640`), which are model-derived and have no
canonical row to read back. Re-fetching would restore the evidence and lose the
extraction, forcing the re-run of model calls that `spec.md:61` exists to avoid.
With a column available, the hybrid ADR-0009 describes has no remaining
motivation at all.

## Revisit triggers

- **#61 becomes ready to ship before the implementing PR lands.** If the
  sequencing above cannot hold, reopen ADR-0009's amendment rather than expose
  the SSE surface under a guarantee that is still false. This trigger is
  mandatory, not advisory.
- **Any non-public document source is ingested before `0006` lands.** ADR-0009's
  bounded-exposure argument is the only thing making the interim window
  tolerable, and it rests entirely on every corpus byte being public SEC filing
  text.
- **Stage payloads outgrow a `jsonb` column.** The object-storage alternative
  returns on its own merits.
- **A service/worker role is introduced.** `db/migrations/README.md:72-76` notes
  no service role exists yet; a new role would need its own grants on
  `extraction_run_steps` including the new column.

## Verification

The implementing PR must show:

1. `0004_extraction_core.sql` byte-for-byte unchanged; the column arrives via
   `0006_*`, which applies cleanly to an empty database in lexical order and
   passes the backup-restore smoke test.
2. `db/migrations/tests/0006_*.test.sql` exercises, under `SET LOCAL ROLE fel_app`
   with `request.jwt.claims` set (`README.md:65-70`): INSERT carrying `output`;
   UPDATE of `output` on an open run succeeds; UPDATE on a terminal run is
   rejected; an identity-pin UPDATE is still rejected; a cross-org read returns
   nothing.
3. **A crash-resume test proving resume succeeds with the `step_completed` event
   never written** — output survives on the step row alone. The absence must be
   produced by drop-on-append, *not* by SQL `DELETE`: `0004:661` grants `fel_app`
   only `SELECT, INSERT` on `extraction_run_events`, and the guard raises
   `'% is append-only'` on DELETE (`0004:488-489`, attached at `0004:523-524`) —
   the same append-only model recorded above. The mechanism already exists:
   `_LosingEventStore`
   (`workers/tests/extraction/test_postgres_crash_resume.py:463-482`, used at
   `:523` via `lose_on_step`) returns an unpersisted event, leaving exactly the
   state a death between the step commit and its append leaves. On a fresh
   connection and fresh stores the resumed pass must assert all three:
   (a) **zero `step_completed` rows** for that step — the precondition query at
   `:547-555`; (b) **output hydrated from `extraction_run_steps.output`** —
   `load_succeeded` returns a non-null `output` with `_load_stage_output`'s event
   scan (`persist.py:701-729`) deleted, so `workflow.py:490-496` skips the stage
   instead of re-executing it; (c) **zero model calls** — `_CountingLLM.calls == 0`
   (`:259-277`), the exact inverse of today's `second.calls >= 1` (`:574`).
   (c) is what stops a resume that silently re-ran the stage from scoring as a
   pass; the counter is whole-run, which is the stronger assertion here because
   every stage resumes from its own row. `stage_resumed` (`workflow.py:497-502`)
   is the per-step seam if one is needed. This is the load-bearing new test and
   the one the current design cannot express.
4. A test asserting that every persisted `extraction_run_events.payload` for a
   full run contains no evidence text, so `data-model.md:23` is machine-checked
   rather than prose.
5. `grep -rn 'stage_output' db/ specs/ packages/contracts/` returns nothing, and
   under `workers/src/` nothing outside `serialize.py`'s function name.
6. `_restore_output`'s `text_hash` check still raises `IntegrityError` on
   tampered text, now sourced from the column.
7. `ensure_extraction_database` applies `0006` to a pre-existing
   `<db>_extraction` database, verified by running the suite twice.
8. `check:generated` passes and the regenerated `api.ts` diff is confirmed — empty
   under Reading A, or its breakage enumerated under Reading B.
9. The full `workers/tests/extraction/` suite green with and without
   `TEST_DATABASE_URL`, including `test_checkpoint_resume.py`,
   `test_resume_evidence_integrity.py`, `test_checkpoint_payload_fidelity.py`,
   `test_stage_audit_fencing.py` and `test_step_failure_record.py`.
10. The PR states legacy-row behaviour explicitly: `_is_recoverable` retained,
    backfill impossibility documented in the `0006` header.

## Notes

**ADR-0009's line citations have drifted, and the drift is worth recording
because a reviewer checking them will otherwise conclude the analysis is wrong.**
Checked individually at `a4bb356` (rebase base after #174; #174 touched only
`accounting.py` and its test — load-bearing citations below are unchanged):

*Still exact:* all six guarantee locations; `0004:143-171`, `0004:661`,
`0004:692-695`; `spec.md:61`; `persist.py:82`;
`events.py:1-8`; `OPERATOR.md:16`; `workflow.py:528-534` (`stage_output` write);
`persist.py:701-729` (`_load_stage_output`).

*Exact but one line short:* `handler.py:263-304`. It resolves to the right
function and carries the claim ADR-0009 makes, but `_bind_evidence_to_spans`
runs to `:305` (`return bound`), so the citation truncates its last line. This
ADR cites the full `:263-305` in "Alternatives rejected" rather than reproducing
the short range. Recorded because "nearly exact" is a third category the
lists either side of it would otherwise hide — a reviewer who checks it
finds real content and stops, and never learns the range is wrong.

*No longer resolving (relative to ADR-0009's original coords):*
`validate/pipeline.py:157,178-180` — the hash chain is now at `:187`, `:196`,
`:208-209`. `workflow.py:370-375` for `stage_input_hash` — now `:477-482`;
`:370-375` is a docstring in `_is_recoverable`. `workflow.py:484` for the
`sha256_hex` re-check — now `:612-618`. `events.py:53-81` for the redaction
docstring — now `:71-116`; `:53-81` no longer names one construct at all, running
from inside the `_REDACT_KEYS` literal (`:52-67`) into that docstring's opening
lines. There is no `_SENSITIVE_KEYS` symbol in the tree.
`persist.py:536-552` — now conflict-upsert code; the checkpoint rationale is at
`:709` and `:822-838`.

**Every one of ADR-0009's substantive claims holds; the coordinates moved**,
consistent with PR #156 (merged `2026-08-04T02:09:06Z`) landing the corrections
its revision history records, and with subsequent merges to `main`. The single
exception is `handler.py:263-304`, which never moved and was one line short from
the day it was written — nothing about #156 explains it. Issue #157's
citations were taken against `61058e4` and have drifted for the same reason. This
ADR's citations are against `a4bb356` and will drift too — which is an argument
for the machine-checked assertions in "Verification" items 4 and 5 over prose
citations wherever a guarantee can be expressed as a test.

Per `AGENTS.md:20,41`, amending `specs/**`, `packages/contracts/**`,
`db/migrations/**` and `docs/handoff/**` requires the `contract-change` label and
an accepted ADR. **This PR ratifies ADR-0011 and marks ADR-0009 superseded
(status header only).** It still does not implement migration `0006`, edit
`persist.py` / `workflow.py` / `events.py`, or change contracts, specs, or
handoff. Those remain the work of the follow-up `contract-change` PR against
#157.
