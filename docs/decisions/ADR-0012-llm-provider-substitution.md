# ADR-0012: Split the AI-provider decision by role, and supersede only ADR-0002's generation-provider clause

Status: Proposed
Date: 2026-08-31
Supersedes: ADR-0002 (`docs/decisions/ADR-0002-mvp-stack.md`, Status: Accepted) —
**the phrase "OpenAI for generation" at `ADR-0002:22` and nothing else.** The
remainder of that same line (the `text-embedding-3` / <= 512-dimension /
`halfvec` embedding pin) is explicitly **left intact and load-bearing**; so is
every other section of ADR-0002. See "Decision" point 1 for the exact split.
Occasioned by: issue #132 ("[M2-CLAIMS] Live 65-question exit gate (close
M2-024)", open, label `agent-task`), which records the replace-OpenAI directive;
finding **A-1** in `specs/004-mvp-completion/clarify-analyse.md:28`; and the
failed Constitution Check at `specs/004-mvp-completion/plan.md:49` with its
Complexity Tracking entry at `plan.md:115`.
Blocks: **M3 and M5 both, and M3 first.** `M3-304`
(`specs/003-agentic-extraction/tasks.md:36`) requires a "live OpenAI
structured-output smoke with approved secret", and it is an acceptance criterion
of #62 (M3-CONFIDENCE-GATE) — so the conflict bites at the milestone gate, not
only at release. Downstream, `RELEASE-LIVE-CUTOVER`
(`specs/004-mvp-completion/spec.md:179-198`) cannot select any provider until
this ADR — or a successor — is ratified. `clarify-analyse.md:28` states the
latter outright: "**Unresolved — needs a superseding ADR before
`RELEASE-LIVE-CUTOVER` selects any provider.**" See "When the conflict bites".

All `file:line` references are verified against this branch's base, `origin/main`
@ `fdcb3d2`. Where a claim could not be verified from the repository, the text
says so at the point of use rather than asserting it. The base is `fdcb3d2`, the
merge commit of PR #173, so the `specs/004-mvp-completion/` files cited
throughout are trunk citations rather than feature-branch ones.

## Context

**Three governing documents give three different answers, and no two of them can
be obeyed at once.**

ADR-0002 is **Accepted**. Its "AI and retrieval" section says, verbatim
(`ADR-0002:22`):

> - OpenAI for generation; `text-embedding-3` embeddings truncated to <= 512
>   dimensions and stored as `halfvec`.

Its change rule says, verbatim (`ADR-0002:47`):

> Product-scope changes require a new specification version. Implementation-stack
> changes require a new ADR with benchmark evidence that the current default
> fails a requirement.

Constitution principle V says, verbatim (`.specify/memory/constitution.md:28`):

> The MVP MUST use the smallest architecture that satisfies measured
> requirements. The locked MVP stack is recorded in
> `docs/decisions/ADR-0002-mvp-stack.md` and MUST NOT be restated elsewhere.
> External services MUST sit behind narrow interfaces. Any stack addition or
> substitution — including microservices, Redis/Celery/Kafka, DuckDB-Wasm,
> **additional AI providers**, and full OpenTelemetry infrastructure — requires
> benchmark evidence and an approved ADR, per the change rule in ADR-0002.

Issue #132 directs the opposite of ADR-0002 for the LLM roles. There is no
superseding ADR and no benchmark evidence. `clarify-analyse.md:28` states the
resulting bind precisely: "Either choice violates something today: following the
directive breaches ADR-0002, following ADR-0002 contradicts a standing
directive." `plan.md:49` records the same as a **failed** Constitution Check:

> - [ ] **The design stays within the approved modular-monolith stack or includes
>   an approved complexity ADR.** — **FAILS.** The replace-OpenAI directive in
>   #132 substitutes `claude-opus-4-8` for ADR-0002's accepted "OpenAI for
>   generation", with no superseding ADR and no benchmark evidence. Principle V
>   requires both.

`specs/004-mvp-completion/spec.md:309` lists the same item in its risk table with
the remediation "Land the superseding ADR before `RELEASE-LIVE-CUTOVER` selects a
provider (finding A-1)". `plan.md:118` orders the remediations: "land the A-1 ADR"
is first. **This ADR is that document, and only that document — it proposes; it
does not amend, and it edits no other file.** Per `AGENTS.md:41`, a change to a
shared path requires an ADR, the `contract-change` label, and integration-lead
review; the ADR comes first.

### What the code actually does today

No live provider of any kind is wired. This is verified, not assumed:

```
git grep -n 'openai\|OpenAI' origin/main -- packages/providers workers/src
```

returns **nothing**. `packages/providers/` contains exactly six files
(`git ls-tree -r --name-only origin/main -- packages/providers`): the protocol
definitions in `fel_providers/interfaces.py`, the deterministic mocks in
`fel_providers/mocks.py`, `__init__.py`, `pyproject.toml`, and two test modules.
**There is no OpenAI adapter, and there is no Anthropic adapter.**

Both provider seams already exist and both fail closed:

- `EmbeddingProvider` (`packages/providers/fel_providers/interfaces.py:56`) and
  `StructuredLLMProvider` (`interfaces.py:47`) are the narrow interfaces
  principle V requires.
- `_resolve_embedding_provider` (`apps/api/app/retrieval.py:135-144`) returns the
  512-dim mock for `'mock'` and raises `UnsupportedEmbeddingProvider` for every
  other pin (`retrieval.py:144`).
- `_resolve_generation_provider` (`retrieval.py:160-164`) does the same, raising
  `UnsupportedGenerationProvider` (`retrieval.py:164`).
- The persisted run identity is pinned to the mock: `GENERATION_PROVIDER = "mock"`
  and `GENERATION_MODEL = "mock-structured-v1"` (`retrieval.py:99-100`).

**This fact governs the whole ADR.** ADR-0002's change rule requires benchmark
evidence that *the current default fails a requirement*. The current default has
never been executed against anything, because no adapter for it exists. See
"Evidence question" below — this is why the ADR is `Proposed` and not `Accepted`.

### When the conflict bites: at M3's gate, not at release

The conflict record frames this as a release-time problem — `clarify-analyse.md:28`
and `plan.md:115` both scope it to `RELEASE-LIVE-CUTOVER`. **That framing is too
late by a milestone, and the ADR records the correction here.**

`specs/003-agentic-extraction/tasks.md:36` reads, verbatim:

> - [ ] **M3-304** Run live OpenAI structured-output smoke with approved secret,
>   provider-failure suite, `make ci`, independent review, and publish immutable
>   eval report.

That task is one of #62's acceptance criteria. #62's body lists under Acceptance:
"Provider failure and **live OpenAI structured-output smoke** pass; `make ci`,
independent review, immutable report pass", and its closing line reads "Request
`FEL_OPENAI_API_KEY` only for credentialed smoke" (`gh issue view 62 -R
wilsonhj/financial-evidence-lab`).

**`M3-304` names OpenAI in its acceptance text.** So the bind is not deferred to
release; it is already sitting on an M3 exit criterion:

- Satisfy `M3-304` as written and the run uses OpenAI for structured generation —
  which is what the #132 directive says not to do.
- Follow the directive and `M3-304` is **unsatisfiable as written**, because the
  artifact it demands is an *OpenAI* smoke. The task text itself would need
  amending, and per `AGENTS.md:41` amending `specs/**` requires an ADR — this one.

Either way #62 cannot close cleanly while the conflict stands. This matters for
sequencing: the ADR must be ratified before **#62** is dispatched, not merely
before `RELEASE-LIVE-CUTOVER` selects a provider. #62 also has the credential
dependency in its own body, so it is the first place the unexercised
approved-secret flow of finding A-4 (`clarify-analyse.md:31`) is actually
exercised.

Note also that #62's acceptance thresholds — "guidance F1 >=90%, KPI/driver F1
>=88%, numeric value/unit/period/sign/scale accuracy >=99%, temporal validity
100%" — are two of the four LLM-sensitive gates this ADR's Arm A uses (guidance
F1 and KPI/driver F1), plus **both** of the two it excludes as deterministic
(numeric accuracy and temporal validity). #62's own eval work is therefore most of Arm A's
apparatus, which is an argument for running the benchmark *as part of* #62 rather
than building a second harness for it.

### Three provider pins ship in the repository, and one contradicts the other two

Two shipped fixtures disagree with each other; only the second disagrees with
ADR-0002:

- `packages/contracts/fixtures/retrieval-trace.json:28-31` pins
  `"embedding_provider": "openai"`, `"embedding_model": "text-embedding-3-small"`,
  `"generation_provider": "openai"`, `"generation_model": "gpt-4.1-mini"`.
- `apps/web/src/lib/observatory/fixtures/synthetic-trace.ts:245-248` pins
  `embedding_provider: "voyage"`, `embedding_model: "voyage-3-large"`,
  `generation_provider: "anthropic"`, `generation_model: "claude-opus-4-8"`.

The first fixture is **consistent** with `ADR-0002:22` and with `ADR-0006:15`
(OpenAI `text-embedding-3-small` at 512 dimensions); it is the second that
contradicts both, on both roles at once.

That second fixture is the only occurrence of `claude-opus-4-8` **in code or
fixtures**, and the only occurrence of `voyage` in any form (`git grep -n -i
'voyage' origin/main`). `git grep -n 'claude-opus' origin/main` returns four
further hits, all prose in `specs/004-mvp-completion/` — `clarify-analyse.md:28`,
`plan.md:49`, `spec.md:213` and `spec.md:309` — which describe this conflict
rather than pin a provider. No runtime code pins either vendor. Two things follow, and both matter:

1. The directive has already leaked into a shipped artifact ahead of its ADR —
   which is the drift this ADR exists to stop.
2. **A third vendor, Voyage, is named in that fixture. It appears in neither
   ADR-0002 nor #132, and has no ADR of any kind.** A reviewer who reads the
   observatory fixture as normative would conclude an embeddings provider has
   already been chosen. It has not been.

## Decision

**1. The supersession is surgical.** This ADR supersedes exactly one clause of
ADR-0002: the phrase **"OpenAI for generation"** at `ADR-0002:22`. Everything
else in ADR-0002 remains in force unchanged, including — and this is the part
most easily lost, because it sits on the *same line* — the embedding storage pin
"`text-embedding-3` embeddings truncated to <= 512 dimensions and stored as
`halfvec`". The <= 512-dimension and `halfvec` half of that sentence is a storage
and index-identity constraint, not a vendor choice, and it is **not** superseded.
Also untouched: the RRF/cross-encoder rule (`ADR-0002:24`), pgvector >= 0.8.2
(`:23`), the data providers (`:28-29`), runtime and operations (`:33-35`), the
revisit triggers (`:39-43`), and the change rule itself (`:47`) — which continues
to bind this ADR and every successor.

**2. The decision splits by role, because the three roles are not substitutable
alike.** ADR-0002 treats "AI and retrieval" as one clause; that is the defect
that makes the conflict look binary when it is not.

**2a. Generation and verification — the directive's actual target.**
`anthropic` / `claude-opus-4-8`, replacing OpenAI for structured generation and
for the verification pass. This is the substitution #132 directs. **It is
proposed here conditionally and is not effective on ratification of this ADR
alone** — see "Evidence question". Principle II is unaffected either way:
"Language models MAY propose or explain assumptions but MUST NOT execute
authoritative financial math" (`constitution.md:19`), so no gate that depends on
decimal arithmetic changes hands with the provider.

**2b. Embeddings (index build and query) — Claude is not an option at all.**
#132 records that Anthropic ships no embeddings endpoint; the exact wording is
quoted under "Notes", along with the caveat that this is a vendor fact this ADR
cannot verify from the repository. The consequence is structural and must be
stated plainly rather than left to be inferred:

> **The stack cannot become single-vendor Anthropic. Whatever is decided,
> embeddings are served by someone other than Anthropic, so the MVP becomes
> multi-provider the moment the generation substitution takes effect.**

Two outcomes are admissible, and **this ADR selects neither**:

- **(i) Retain OpenAI `text-embedding-3-small@512` for embeddings alone.** The
  stack is then OpenAI-for-embeddings plus Anthropic-for-generation. **The
  consequence is that the OpenAI credential remains required.**
  `docs/handoff/CREDENTIALS.md:9` — "| OpenAI API key | provider integration
  test | CI/deployment secrets only | Not requested |" — stays, and a second row
  for the Anthropic key is added beside it. `RELEASE-LIVE-CUTOVER` must then
  provision **two** external AI credentials, not one. This bears directly on
  finding **A-4** (`clarify-analyse.md:31`), which records that all five
  credential groups read "Not requested", so the approved-secret flow principle
  IV requires "has never been exercised".
- **(ii) Select a third embeddings provider by benchmark.** #132's candidates are
  `text-embedding-3-small@512`, `nomic-embed-text-v1.5@512` (self-hosted), and
  optionally `bge-m3` (manually truncated). If a permissive self-hostable model
  clears the Recall@10 gate, the OpenAI credential can be **retired entirely**
  and Anthropic becomes the only external AI dependency. That is #132's stated
  preference, but it is a *hypothesis about a measurement that has not been
  taken*, not a decision this ADR is entitled to make.

**Outcome (ii) is not this ADR's to ratify.** Retiring `ADR-0002:22`'s
`text-embedding-3` pin supersedes the embeddings half of the clause this ADR
explicitly leaves intact, so it needs the separate embeddings ADR #132
anticipates; what Arm B produces here is the evidence that ADR would rest on, not
the decision itself. Subject to that, the choice between (i) and (ii) is deferred
to the benchmark, deliberately.
`ADR-0002:22`'s <= 512 / `halfvec` constraint survives either way and constrains
both: `DIMENSIONS = 512` (`packages/retrieval/fel_retrieval/index_version.py:21`)
is hashed into the index identity.

**2c. Reranking — checked; no provider is assigned, so there is nothing to
supersede.** Neither ADR-0002 nor ADR-0006 names a vendor for reranking.
`ADR-0002:24`: "Reciprocal rank fusion (RRF) is the first-stage fusion method. A
cross-encoder reranker is added only if the frozen-benchmark Recall@10 gate
fails". `ADR-0006:14`: "A no-op reranker interface ships. If the checksum-frozen
M2 smoke baseline Recall@10 is below 90%, add a cross-encoder over the fused top
100 as ADR-0002 requires." The trigger is encoded in code as
`RERANKER_RECALL_TRIGGER = Decimal("0.90")`
(`packages/retrieval-evals/fel_retrieval_evals/metrics.py:60`). Reranking is
therefore **out of scope for this ADR** — but note the live wire: if the
embeddings benchmark returns Recall@10 < 90%, the cross-encoder path activates
and *that* introduces a new provider decision, which will need its own evidence
and its own ADR. It does not get to ride in on this one. Recorded as a revisit
trigger.

**3. The index-identity pins are not superseded and must not be treated as
soft.** `index_version_id` (`index_version.py:25-46`) hashes
`(corpus_version_id, config_hash, provider, model, dimensions, distance)` into a
UUIDv5, and the module docstring states the contract: "an identical pinned build
reuses/resumes the same row and any changed pin mints a new id"
(`index_version.py:6-7`). ADR-0006:11 makes the row immutable. **The embeddings
choice is therefore close to a one-way door — changing it later forces a full
corpus re-embed and a new index version — while the generation choice is not.**
That asymmetry is the strongest argument for deciding the two roles on separate
evidence and separate timelines, and it is why 2b defers rather than guesses.

## Evidence question (open; this ADR does NOT have what principle V demands)

**This is the section that decides whether this ADR deserves ratification, and it
must be read before the Consequences.**

Principle V requires "benchmark evidence and an approved ADR"
(`constitution.md:28`). ADR-0002's change rule is more specific still: "a new ADR
with **benchmark evidence that the current default fails a requirement**"
(`ADR-0002:47`).

**This ADR does not have that evidence. None exists in the repository.** An ADR
that asserted a substitution without it would commit precisely the defect it was
written to correct — it would become a second unevidenced provider directive,
differing from #132 only in filename.

Worse, and this is the part the conflict record does not yet state: **the
required evidence cannot currently be produced at all.** The change rule demands
a measurement of the *current default* failing. The current default is
`OpenAI for generation`. No OpenAI adapter exists (`git grep -n 'openai\|OpenAI'
origin/main -- packages/providers workers/src` → no output), and every non-mock
pin raises (`retrieval.py:144,164`). The current default has never been run, so
it has not been measured, so it cannot yet be shown to fail. Ratifying a
substitution today would not be a judgement call made on thin evidence — it would
be a judgement made on *no* evidence, about an incumbent that has never been
given the opportunity to fail.

Note also that the existing eval gate cannot settle this in its present form.
`SMOKE_THRESHOLDS` (`metrics.py:53-59`) already encodes five gate metrics, but
ADR-0010:32-35 records that the smoke gate "scores perfect on the controlled
corpus" and "therefore discriminates nothing yet". A benchmark that every
candidate passes is not evidence. The corpus pin #132 requires is a precondition
of the measurement, not a nicety.

### The benchmark that would settle it

Run #132's live 65-question exit gate — the one that closes M2-024 — on the
**pinned real EDGAR corpus** (#132 requires sourcing the actual filings the 65
questions cite, checksum-pinning them, and setting the manifest `resolved=true`;
it is `resolved=false` today). Run it as a **two-arm comparison at temperature 0
with structured outputs**, holding the corpus, chunker config, index config and
question set fixed, and varying only the provider under test. Record model,
config and cost provenance alongside every metric, as #132 separately requires.

**Arm A — generation and verification (LLM-sensitive gates).** Same embedder in
both arms; vary only the generation provider between OpenAI and
`claude-opus-4-8`. Judge against `specs/001-financial-evidence-lab/spec.md`
§19.6 "Release gates" (`spec.md:1024-1041`), on the four LLM-sensitive rows:

| Gate | Threshold | `spec.md` line |
|---|---:|---|
| Citation entailment precision | >= 95.0% | `spec.md:1032` |
| Guidance extraction F1 | >= 90.0% | `spec.md:1035` |
| KPI/revenue-driver extraction F1 | >= 88.0% | `spec.md:1036` |
| Unsupported-answer abstention precision | >= 95.0% | `spec.md:1038` |

**Arm B — embeddings (retrieval-sensitive gate).** Same generation provider in
every run; vary only the embedder across #132's candidates, each truncated to the
repository's 512-dimension cap. Judge against the one embeddings-sensitive row:

| Gate | Threshold | `spec.md` line |
|---|---:|---|
| Retrieval Recall@10 | >= 90.0% | `spec.md:1034` |

`spec.md:1041` is unambiguous about the standing of these numbers: "No release is
promoted if any gate fails." Constitution principle III makes §19.6 "mandatory"
(`constitution.md:22`).

Two gates deliberately sit outside both arms. Temporal-validity (100%,
`spec.md:1030`) and numeric accuracy (>= 99.0%, `spec.md:1031`) are enforced by
deterministic decimal computation and cutoff logic under principle II
(`constitution.md:19`), not by the model; a provider swap that moved either would
indicate a defect in the pipeline rather than a difference between vendors, and
should be investigated as such rather than scored as provider evidence. Citation
completeness (>= 92.0%, `spec.md:1033`) is jointly sensitive to retrieval and
generation, so it should be **recorded in both arms but attributed in neither**.

### What each outcome licenses

- **The incumbent clears every gate in its arm.** The change rule is not
  satisfied — nothing has failed a requirement — and the corresponding half of
  this ADR must be **withdrawn**, not accepted. A preference for a different
  vendor is not a licence under `ADR-0002:47`, however strongly it is held.
- **The incumbent fails a gate its challenger clears.** The change rule is
  satisfied for that role. The evidence is appended to this ADR and the
  integration lead may ratify that role's substitution — that role only.
- **Both fail.** Neither provider question is the live one; the gate failure is
  the finding, and it belongs to the pipeline, not to procurement.

Until Arm A runs, the honest status of the generation substitution is **directed
but unevidenced**, and this ADR says so rather than papering over it.

## What must change (and what must not)

If ratified, the following must change — and each item is a real edit that a
subsequent PR owns, not a note:

- **`docs/handoff/CREDENTIALS.md`.** The registry has **five rows and no
  Anthropic row at all** (`CREDENTIALS.md:5-11`; `git show
  origin/main:docs/handoff/CREDENTIALS.md | grep -i 'anthropic\|claude'` returns
  nothing). An Anthropic API key row must be added. The OpenAI row
  (`CREDENTIALS.md:9`) is **retained under outcome (i)** and retired only if
  outcome (ii) selects a self-hosted embedder. `docs/handoff/STATUS.md:167` names
  the concrete variable in use today — `FEL_OPENAI_API_KEY` — and its instruction
  ("Request ... only for the explicitly credentialed live retrieval/extraction
  smoke gates") must be extended, not replaced, under outcome (i).
- **`specs/003-agentic-extraction/tasks.md:36` (`M3-304`).** Its acceptance text
  names a "live OpenAI structured-output smoke". If generation moves to
  `claude-opus-4-8`, that task is unsatisfiable as written and must be re-worded
  to name the ratified provider — or, better, to name the *role* rather than the
  vendor, so the next substitution does not require a spec edit. Same for #62's
  issue body, which repeats the phrase and pins `FEL_OPENAI_API_KEY`. This is a
  `specs/**` edit and is gated by `AGENTS.md:41`.
- **`RELEASE-LIVE-CUTOVER`'s provider decision.** The package is proposed for
  registration at `specs/004-mvp-completion/spec.md:179-198` and absorbs #132
  (`clarify-analyse.md:16`). Its provisioning list becomes two AI credentials
  under outcome (i), one under outcome (ii).
- **`packages/providers/**`.** The protocols already exist and need no change
  (`interfaces.py:47,56`); what is missing is any adapter. Note the ownership
  gap, already flagged at `STATUS.md:117`: #62 owns the live OpenAI adapter
  deferred from #60, but its `allowed_paths` (`workstreams.yaml:363-366`) are
  `workers/src/fel_workers/extraction/**`, `workers/tests/**`, `evals/**` —
  **`packages/providers/**` is not among them**, and that is where the provider
  protocol lives. Whoever implements an adapter needs that path granted or a
  different owner.
- **`apps/api/app/retrieval.py`.** `GENERATION_PROVIDER`/`GENERATION_MODEL`
  (`:99-100`) and both resolvers (`:135-144`, `:160-164`) gain a live branch. The
  fail-closed default must survive: an unwired pin must keep raising rather than
  silently falling back to the mock.
- **The two contradictory fixtures**, `retrieval-trace.json:28-31` and
  `synthetic-trace.ts:245-248`, must be reconciled to whatever is ratified. The
  `voyage` / `voyage-3-large` values in the latter must either be justified by an
  ADR or removed; they are currently ungoverned.
- **The other documents that restate the pin.** `constitution.md:28` says the
  locked stack "MUST NOT be restated elsewhere"; it is restated in five places,
  so superseding `ADR-0002:22` alone does not finish the job. For the generation
  role: `ADR-0007:16` (**Status: Accepted**) — "The OpenAI adapter uses JSON
  Schema Structured Outputs and records provider/model/response/usage/refusal
  metadata" — and `ADR-0007:30`; `specs/003-agentic-extraction/spec.md:204` ("The
  first live provider is OpenAI structured output behind an additive provider
  interface") and `:190`; and `specs/001-financial-evidence-lab/spec.md:512`.
  Under outcome (ii) additionally `ADR-0006:15` and
  `specs/002-observable-hybrid-retrieval/spec.md:53` (M2-FR-003), both of which
  the separate embeddings ADR would own. Leaving `ADR-0007:16` unamended would
  leave an **Accepted** ADR pinning OpenAI for the very role this one moves.
- **`ADR-0002` itself** gains a `Superseded (in part):` line naming this ADR and
  scoping it to the "OpenAI for generation" clause of `:22`. Per ADR-0011's
  precedent, that insertion shifts subsequent line numbers — any PR citing
  ADR-0002 by line across that edit must say which side of the move it cites.

The following must **not** change, and a PR that changes them is out of scope:

- Every other clause of ADR-0002, itemised in Decision point 1.
- The <= 512-dimension / `halfvec` / cosine pins and the immutable index identity
  (`index_version.py:21-22,25-46`; ADR-0006:11).
- RRF as first-stage fusion and the no-op reranker
  (`ADR-0002:24`, `ADR-0006:14`).
- The §19.6 gate thresholds themselves (`spec.md:1028-1039`). **A provider
  substitution may not be accompanied by a threshold relaxation** — that would
  make the benchmark unfalsifiable and convert this ADR into the rubber stamp it
  is written to avoid.
- Principle II's prohibition on models executing authoritative financial math
  (`constitution.md:19`).

## Consequences

- **The stack becomes multi-provider, and principle V's simplicity limb takes a
  real cost.** Under outcome (i) production depends on two external AI vendors
  where ADR-0002 contemplated one. This is a genuine loss, not a formality, and
  it is the strongest argument against this ADR (see "Alternatives rejected").
- **`RELEASE-LIVE-CUTOVER` becomes able to select a provider without violating
  the constitution** — but only once the Arm A/Arm B evidence is appended.
  Ratifying this ADR *without* that evidence would unblock the package by fiat
  and re-open finding A-1 under a new number.
- **Finding A-1 is resolved only in form until the benchmark runs.**
  `clarify-analyse.md:28` asks for "a superseding ADR"; the substance it is
  standing in for is the evidence, not the file.
- **The `claude-opus-4-8` model id becomes a real pin.** Today it exists only in
  one web fixture (`synthetic-trace.ts:248`). Once pinned in
  `GENERATION_MODEL`, it enters persisted run lineage (`retrieval.py:96-100`
  calls this "immutable lineage"), so a later model-id change mints new identity
  the same way an embedder change does.
- **The OpenAI credential's fate is decided by Arm B, not by Arm A.** A reader
  who takes "replace OpenAI" at face value will expect the OpenAI row to be
  deleted from `CREDENTIALS.md`. Under outcome (i) it is not, and that
  expectation gap is the single most likely source of a botched cutover.
- **#62 cannot close cleanly until this is ratified, and that is the earliest
  binding consequence.** `M3-304` (`tasks.md:36`) names an OpenAI smoke in an
  acceptance criterion #62 inherits; ratifying the directive makes that task
  unsatisfiable as written and obliges the amending PR to rewrite it. This ADR
  does not by itself unblock #62 for dispatch — it remains `blocked`
  (`STATUS.md:101,117`: it `depends_on: [M3-REVIEW]` and has no `status` key, so
  it inherits `defaults.status: blocked`) and its `allowed_paths` gap stands
  (`workstreams.yaml:363-366`) — but it removes the governance obstacle that
  would otherwise make #62's exit criteria contradictory whichever provider it
  used.
- **`M3-304`'s task text must be amended if the substitution is ratified**, and
  that amendment touches `specs/**`, which `AGENTS.md:41` gates behind an ADR and
  a `contract-change` label. It is listed under "What must change".

## Alternatives rejected

- **Keep ADR-0002 at full strength; treat #132's directive as not yet
  authorised.** *This is the strongest alternative, and the case for it is
  genuinely good.* (1) It is what principle V's text most directly supports
  today: a substitution "requires benchmark evidence and an approved ADR", and
  there is no evidence, so on a plain reading the substitution is simply not yet
  licensed. (2) **The directive may well predate information the benchmark would
  supply.** #132 itself demonstrates this pattern within its own body: its
  rationale reports "Corrected numbers from fact-check" and records that
  `text-embedding-3-large` is "≈64.6 (NOT ~69)" and that "The paid-cloud quality
  moat is smaller than it looks" — an earlier belief revised once checked. A
  directive formed before its own fact-check deserves the same scrutiny it
  applied to the embedder numbers. (3) **A multi-provider stack contradicts
  principle V's simplicity limb** — "the smallest architecture that satisfies
  measured requirements" — and outcome (i) leaves the project depending on two
  external AI vendors where ADR-0002 needed one, which is strictly larger. (4)
  The incumbent has never been shown to fail anything.
  **Why it is not adopted here:** it does not resolve the conflict; it picks a
  side. #132 remains open and standing, is already shaping provider work
  (`plan.md:115`), and has already leaked a pin into a shipped fixture
  (`synthetic-trace.ts:245-248`). Leaving the directive unaddressed leaves the
  drift running silently, which is worse than adjudicating it in the open.
  **But note what follows from taking this alternative seriously: if Arm A never
  runs, or runs and the incumbent clears every gate, this ADR must be withdrawn
  rather than accepted.** That is the honest terminus of the argument above, and
  it is recorded as a revisit trigger rather than buried here.
- **Supersede the whole of ADR-0002's "AI and retrieval" section.** Rejected as
  over-broad. The section's other clauses — the 512/`halfvec` pin, pgvector
  >= 0.8.2 with its CVE fix (`ADR-0002:23`), RRF and the cross-encoder trigger
  (`:24`) — have nothing to do with the provider dispute and carry their own
  independent justification. Superseding them wholesale would silently reopen
  three settled decisions.
- **Decide the embeddings provider now.** Rejected on #132's own reasoning and on
  the index-identity mechanics: #132 marks benchmark-selection of the embedder as
  "blocks everything else" within it, and the pin is near-irreversible
  (`index_version.py:6-7`). Choosing here would repeat the exact error — deciding
  a provider by preference — that this ADR exists to correct, and would do it on
  the one role where the mistake is most expensive to undo.
- **Adopt `voyage-3-large`, as `synthetic-trace.ts:246` already implies.**
  Rejected. A UI fixture is not a decision record. Voyage appears in no ADR, is
  absent from #132's candidate list, and has never been benchmarked here. If it
  is a serious candidate it enters Arm B like any other.
- **Record a principle-V waiver in `plan.md`'s Complexity Tracking instead of
  writing an ADR.** Rejected: principle V requires "an approved ADR" by name, and
  `plan.md:118` already orders "land the A-1 ADR" first among the remediations. A
  waiver would also be far less discoverable than `docs/decisions/`, which is
  where a future reader will look.
- **Ratify the generation substitution now and defer only embeddings.**
  Superficially attractive, since Arm A is the reversible half. Rejected because
  the change rule's condition — evidence that the current default fails — is
  unmet for *both* roles equally, and the reversibility of a decision is not a
  substitute for the evidence the governing rule demands.

## Revisit triggers

- **The Arm A / Arm B benchmark runs.** This ADR is then either ratified with the
  evidence appended, narrowed to the role the evidence supports, or **withdrawn**.
  This trigger is mandatory: an indefinitely `Proposed` provider ADR reproduces
  the ambiguity that A-1 records.
- **Any live provider is wired before that benchmark runs** — that is, any commit
  after which `git grep -n 'openai\|OpenAI\|anthropic\|Anthropic' origin/main --
  packages/providers workers/src apps/api/app` is non-empty. The ADR's central
  premise (no adapter exists, so the incumbent has never been measured) would no
  longer hold.
- **Recall@10 comes in below 90%** (`spec.md:1034`; `RERANKER_RECALL_TRIGGER`,
  `metrics.py:60`). The cross-encoder path activates, introducing a reranking
  provider decision that Decision point 2c deliberately leaves uncovered.
- **A provider named in neither ADR-0002 nor #132 appears outside a fixture** —
  Voyage being the live instance today (`synthetic-trace.ts:245-246`).
- **#62 is dispatched before this ADR is ratified.** Its `M3-304` acceptance
  criterion (`tasks.md:36`) names an OpenAI smoke, so dispatching it under the
  unresolved conflict hands an agent a task that cannot be completed without
  breaching either ADR-0002 or the directive. This trigger is mandatory.
- **#132 is closed, superseded, or its embeddings finding is contradicted** —
  in particular if Anthropic ships an embeddings endpoint, which would collapse
  the role split this ADR is built on and permit a genuinely single-vendor stack.
- **`ADR-0002:47`'s change rule is itself amended.** Every argument in the
  "Evidence question" section is downstream of its exact wording.

## Verification

The ratifying PR must show:

1. The 65-question live gate run on the checksum-pinned real EDGAR corpus with
   the manifest at `resolved=true`, with all five `SMOKE_THRESHOLDS` metrics
   (`metrics.py:53-59`) recorded against their thresholds — not the single seeded
   smoke query, which #132 explicitly excludes as the gate.
2. **Arm A** results for both generation providers on the four LLM-sensitive
   gates (`spec.md:1032,1035,1036,1038`), at temperature 0 with structured
   outputs, embedder held constant.
3. **Arm B** Recall@10 (`spec.md:1034`) for each candidate embedder truncated to
   512 dimensions, generation provider held constant.
4. Model, config and cost provenance recorded alongside every metric, per #132.
5. A statement of how non-determinism was handled — single recorded run versus a
   variance band — given that the thresholds are exact `Decimal` comparisons
   (`metrics.py:53-59`).
6. The output of `git grep -n 'openai\|OpenAI' origin/main -- packages/providers
   workers/src` at the ratification commit, so the "no adapter exists" premise is
   re-checked rather than inherited from this draft.
7. `CREDENTIALS.md` updated to match the ratified outcome: an Anthropic row
   added, and the OpenAI row (`:9`) either retained with a stated reason
   (outcome (i)) or retired with the Arm B evidence that permits retiring it
   (outcome (ii)).
8. `ADR-0002` carrying a `Superseded (in part):` line scoped to the "OpenAI for
   generation" clause of `:22`, with the rest of `:22` explicitly preserved.
9. The index-identity consequence stated: whether the ratified embedder changes
   `provider`/`model` in `index_version_id` (`index_version.py:25-46`) and, if
   so, that a full re-embed and new index version are budgeted.
10. `retrieval-trace.json:28-31` and `synthetic-trace.ts:245-248` reconciled to
    the ratified decision, with the ungoverned `voyage` values resolved.
11. `plan.md:49`'s Constitution Check flipped with a reference to this ADR, and
    `clarify-analyse.md:28`'s A-1 status updated — neither of which this ADR
    edits.
12. `M3-304` (`specs/003-agentic-extraction/tasks.md:36`) re-worded to match the
    ratified provider, and #62's issue body updated in step, so no acceptance
    criterion still names a provider the ADR has superseded.

## Notes

**What #132 actually says about embeddings.** The load-bearing sentence, verbatim
from the first checklist item of `gh issue view 132 -R
wilsonhj/financial-evidence-lab`:

> **Select the EMBEDDINGS provider by BENCHMARK, not by taste (blocks everything
> else).** Anthropic has no embeddings endpoint, so index build + query embedding
> **cannot** use Claude; generation + verification use `claude-opus-4-8` per the
> replace-OpenAI directive, but that only covers the LLM roles. Rather than pick a
> provider up front, **run this issue's 65-Q Recall@10 gate across 2-3 candidate
> embedders truncated to the repo's 512-dim cap and pin by measured recall on the
> real EDGAR corpus.** Candidates: `text-embedding-3-small@512`,
> `nomic-embed-text-v1.5@512` (self-hosted), and optionally `bge-m3` (manually
> truncated).

And on supersession, from the same issue's checklist:

> **If a permissive self-hostable model clears the gate, promote it to the single
> production + CI default** and supersede ADR-0002's OpenAI embeddings pin with a
> new ADR carrying the benchmark evidence. Keep OpenAI as a documented
> *alternative* `EmbeddingProvider`, not the pinned default.

Note that #132 anticipates superseding **ADR-0002's embeddings pin** — a step
this ADR pointedly does *not* take, because the evidence that would license it
has not been produced. #132 is explicit that the supersession comes *with* the
benchmark evidence, not before it.

**Claims this ADR does not verify, and does not assert.**

- **That Anthropic ships no embeddings endpoint.** This is #132's assertion,
  quoted above, and it is the premise of the entire role split. It is a vendor
  fact about an external service and **cannot be verified from this repository**.
  What *is* verifiable is that the repository contains no Anthropic embeddings
  adapter and no reference to one (`git grep -n -i 'anthropic' origin/main --
  packages/providers workers/src apps/api` returns nothing; the only `anthropic`
  string in code or fixtures is `synthetic-trace.ts:247`, a `generation_provider`
  field, the other occurrence being prose at
  `specs/004-mvp-completion/spec.md:213`).
  The ratifying PR should confirm the vendor fact against current provider
  documentation rather than inheriting it from an issue opened 2026-07-21.
- **#132's MTEB figures** (`3-small ≈62.3`, `nomic-v1.5 ≈62.3`, `Qwen3-0.6B
  ≈64.3`, `bge-m3 ≈63`, `text-embedding-3-large ≈64.6`) and its licensing claims
  (`nomic-embed-text` Apache-2.0, `bge-m3` MIT, `jina-embeddings-v3` and
  `NV-Embed-v2` CC-BY-NC) are reproduced from the issue and **not independently
  checked here**. They are inputs to Arm B's candidate selection, not evidence.
  Arm B replaces them with measurements on this corpus, which is the point.
- **That `claude-opus-4-8` is a currently available model id.** Not verifiable
  from the repository; its sole occurrence is a fixture
  (`synthetic-trace.ts:248`). The ratifying PR must confirm the id before pinning
  it into persisted lineage (`retrieval.py:99-100`).

**Format.** This ADR matches ADR-0011
(`docs/decisions/ADR-0011-extraction-step-output-column.md`): unbolded
`Status:` / `Date:` / `Supersedes:` / `Occasioned by:` / `Blocks:` metadata, the
verified-against-base paragraph, and the section set Context / Decision / an
open-question section / What must change (and what must not) / Consequences /
Alternatives rejected / Revisit triggers / Verification / Notes. ADR-0010 uses
**bolded** metadata keys; ADR-0009 and ADR-0011 do not, and the two most recent
ADRs set the house convention followed here. The "Evidence question (open; ...)"
heading follows the precedent of ADR-0009's and ADR-0011's "Contract-version
question (open; ...)" — a named, unresolved question the ratifying PR must answer
rather than inherit.

**Scope.** Per `AGENTS.md:41` and the precedent set by ADR-0009's closing note,
**this ADR proposes the change and does not make it.** No specification,
contract, credential registry, workstream, or source file is edited by the commit
that adds it; `docs/decisions/ADR-0012-llm-provider-substitution.md` is the only
file it creates or touches.
