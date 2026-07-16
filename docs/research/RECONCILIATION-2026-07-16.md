# PR #74 / #75 research reconciliation audit

Audited against GitHub `main` at `70ee86fd4ff1a4bc9abe54bc0e0f56144566bc89` on 2026-07-16. This is a read-only audit; no repository or GitHub state was changed.

## Recommendation

Create one main-based reconciliation branch, suggested name `chore/reconcile-m2-m3-research`, and one narrowly scoped PR. Recover the four artifact files from the final reviewed heads, not from either merge commit or branch history. The paths do not overlap existing `main` content and have no code dependency, so the file recovery itself is low-conflict.

Do **not** merge `agent/ext-benchmark-seed` or `agent/ext-ontology-research` into `main`, and do not cherry-pick merge commits `a549fbf2b2609d5f753add8173ade414e0a991bc` or `bb74aa31f3f49b35d676bc7384b6f77e79d90e4c`. Both heads have diverged from current `main` (3 commits ahead, 50 behind, merge base `11a59c7677316f7b911b255d687b36953be4f4fa`), so merging history risks importing retired `integration/m0` ancestry.

Two safe recovery options exist:

1. Preferred: copy the four blobs from the exact final heads into a fresh main-based branch and commit them as a single provenance-preserving reconciliation change.
2. Also safe but noisier: cherry-pick only the four path-scoped commits in dependency order: `c2fae2e` then `cf4b702`, and `0120088` then `4ee4129`. Do not cherry-pick any other branch or merge commit.

The benchmark seed is structurally sound enough to recover as a **candidate M2 smoke dataset**. The ontology survey should be recovered only as **research draft**, with the corrections below included before it is treated as authoritative input to T0301.

## Exact missing artifacts and provenance

All four paths return 404 on current `main`.

| Artifact | Final source head | Source blob | Size / lines | Commit provenance |
|---|---|---|---:|---|
| `evals/datasets/benchmark-seed/README.md` | `cf4b7021241b3bf4c18291a3d62ff2ae64468f02` | `6ce25b221a7bf506ee11ff1297bc9a0088c7ed99` | 6,688 bytes / 138 content lines | Added by `c2fae2ef1cebac6eb56d171344201cd2ce9eecd5` |
| `evals/datasets/benchmark-seed/questions.jsonl` | `cf4b7021241b3bf4c18291a3d62ff2ae64468f02` | `2ca0cadea22cc54f2dd004e8fc60127e78518ec4` | 57,053 bytes / 65 JSONL records | Added by `c2fae2ef1cebac6eb56d171344201cd2ce9eecd5`; BM-0045 corrected by final commit `cf4b7021241b3bf4c18291a3d62ff2ae64468f02` |
| `docs/research/ontology/README.md` | `4ee412969622c2d2969ba2917540ad908824b6ac` | `7804a7246cc43920723b9d16ac4d0bbb1471259f` | 6,671 bytes / 106 content lines | Added by `01200882502b568552809f920236260ac4698c54` |
| `docs/research/ontology/saas-disclosure-survey.md` | `4ee412969622c2d2969ba2917540ad908824b6ac` | `6c98920e4350ee394d1c19023dea048820233819` | 39,698 bytes / 642 content lines | Added by `01200882502b568552809f920236260ac4698c54`; FIVN/PAYC corrections in final commit `4ee412969622c2d2969ba2917540ad908824b6ac` |

PR #74 final merge commit: `a549fbf2b2609d5f753add8173ade414e0a991bc`. PR #75 final merge commit: `bb74aa31f3f49b35d676bc7384b6f77e79d90e4c`. These merge SHAs are historical references only, not recommended recovery inputs.

## PR #74 benchmark seed: offline verification

Recomputed directly from final blob `2ca0cade...`:

- 65 unique, parseable JSONL records.
- Category counts exactly match the README: exact fact lookup 12; guidance extraction 8; revenue-driver extraction 7; filing-section retrieval 6; table reasoning 6; insufficient evidence 6; contradiction detection 5; multi-period comparison 5; temporal cutoff trap 5; restatement handling 5.
- 59 answerable and 6 unanswerable records.
- 42 numeric answers and 17 text answers; numeric values are strings.
- 73 non-empty evidence objects across 24 distinct accession numbers.
- 16 distinct issuers, all in current `evals/datasets/issuer-cohort.json` version 1 (`as_of` 2026-07-13), with zero ticker/CIK mismatches.
- No duplicate IDs, missing required top-level fields, malformed accession formats, non-UTC `as_of` strings, invalid answerable/unanswerable structure, or invalid draft-adjudication structure.
- The reviewed BM-0045 citation defect is fixed in final head `cf4b702`: the cited quote now contains the asserted `$3.700 billion to $3.708 billion` range.

The previous integration review also independently recomputed all 11 offline acceptance criteria and verified the arithmetic for the six derived numeric questions. Those results are consistent with this audit.

### Benchmark corrections / gates still required

1. **Fix timestamp semantics before using this as a temporal benchmark.** All records use exact ISO timestamps, commonly midnight UTC. The canonical spec says evidence is eligible only when its applicable public-availability timestamp is `<= cutoff`. Several records visibly cite a filing issued on the same calendar date as an `as_of` of `00:00:00Z` (for example BM-0001/BM-0010 on 2026-05-28), which is likely earlier than the SEC acceptance/publication time. Resolve every record against actual `accepted_at`/`published_at`; use actual availability timestamps or a later explicit cutoff. Do not silently reinterpret timestamp fields as dates.
2. **The 73/73 byte-presence claim is not reproducible offline.** The fetched filing bytes, content hashes, verification script, and provenance log were not committed. Either add a small verification manifest/script with accession, document URL, acceptance timestamp, and content hash, or soften the README to identify byte verification as an author-reported result.
3. **Re-verify the six insufficient-evidence cases.** Each currently records one reviewed 8-K. Absence claims should also cover the corresponding 10-Q and any other document publicly available before `as_of`, particularly Zoom/Workday RPO and MongoDB NRR.
4. **Keep the dataset labeled candidate/draft.** It is a high-quality seed for T0214a, not completion of T0214a by itself. The task still requires an executable evaluation harness and M2 gate automation. M5 dual adjudication is explicitly deferred to T0214b.
5. **Decide range representation in the M2 contract.** Numeric guidance ranges are encoded as a hyphenated string in `value`. Freeze either this representation or explicit `low`/`high` fields in the M2 benchmark schema before implementation agents consume it.

## PR #75 ontology research: offline verification

At final head `4ee4129`, the document passes its countable structural bars:

- 16 of 20 issuers have accession-cited narrative claims (the stated minimum was 15).
- 10 normalized metrics across 9 families, each with at least 3 cited examples.
- A 14-row by 7-field machine-consumable metric table.
- Exactly 10 issuer-vs-issuer definitional conflicts.
- A prior independent census found zero CIK/accession/form mapping mismatches across 86 citation instances.
- The two original review defects were corrected: FIVN's `ContractWithCustomerLiabilityNoncurrent` result is recorded as present, and PAYC is consistently described as dual-convention.

### Ontology corrections required before acceptance

1. **Correct the 20/20 rigor claim.** APPF, FIVN, PAYC, and PCTY have no accession-cited narrative claims. Scan their latest 10-K MD&A and earnings releases, add cited disclosures or document genuine absence with reviewed accessions. FIVN, PCTY, and PAYC retention disclosures are specifically high-value checks.
2. **Cite or remove roughly 13 issuer-specific assertions.** These include Family 7's `Also OKTA, TEAM, APPF...` and `as do MDB, FIVN, PCTY` statements; Family 1 negative claims for NOW/WDAY/SNOW/HUBS/TWLO; the ZS renewal-assumption and SNOW services-gross-loss statements; and vague `most issuers` language.
3. **Fix the Family 7 roll call.** It names SNOW, DDOG, ZM, and TEAM without RPO-family citations. Six properly cited issuers already satisfy the count gate; do not inflate the list.
4. **Remove or qualify unreproducible integrity claims.** `sec/sec_fetch.sh` and `sec/provenance.jsonl` are referenced but absent. The claimed 48/48 normalized-byte verification rests on unrecoverable authoring-session state. Commit a sanitized, deterministic verifier and provenance/content-hash manifest under `docs/research/ontology/`, or relabel the result author-reported.
5. **Remove the hard-coded personal email from the README.** Replace the literal SEC User-Agent identity with a project-managed/configurable placeholder and document that a valid organizational contact is required at execution time.
6. **Perform targeted source spot checks before calling the research accepted:** DDOG ARR wording, TEAM `$10k Cloud ARR`, PD deferred-revenue rollforward, OKTA margin/cRPO, post-cutoff figures, the `0001193125` filing-agent accession plausibility, and a fresh diff of all 120 companyconcept probes against Part 3.
7. Change `Status: COMPLETE` to `Status: RESEARCH DRAFT` until these corrections and evidence checks land.

## Stale references and dependencies

- Issues #71 and #73 are closed historical work items; retaining their numbers in artifact headings is acceptable provenance.
- `T0214a`, `T0214b`, and `T0301` are still current task IDs on `main`.
- `evals/datasets/issuer-cohort.json` exists on `main`, and the benchmark's 16 issuer mappings agree with it.
- Current `docs/handoff/EXTERNAL_AGENT_BRIEF.md` still instructs agents to base work on retired `integration/m0`. Neither recovered artifact needs that instruction to function, so avoid touching this shared path in the minimal reconciliation PR. File/update the handoff document separately under integration-lead rules if it remains an active entrypoint.
- The artifacts do not depend on application code, migrations, generated contracts, or package installation.

## Suggested reconciliation PR contents

Allowed paths:

```text
evals/datasets/benchmark-seed/**
docs/research/ontology/**
```

Suggested PR sequence:

1. Snapshot the four exact final-head files.
2. Record source PR/head/blob provenance in the PR body.
3. Apply the README status/privacy/stale-claim corrections and the benchmark timestamp checks. If SEC-backed checks cannot be completed in the same PR, mark those claims provisional and open bounded follow-up issues; do not represent them as verified.
4. Add offline dataset validation and a reproducible source-verification manifest/script if available.
5. Run repository CI and request independent review.

No ADR or contract-change label is needed merely to restore these non-shared data/research paths. A later PR that freezes the benchmark answer schema or generates `packages/ontology/**` contracts should use the appropriate contract-change/ADR process.

## Validation commands after recovery

Verify the untouched source snapshot before intentional edits:

```bash
test "$(git hash-object evals/datasets/benchmark-seed/README.md)" = 6ce25b221a7bf506ee11ff1297bc9a0088c7ed99
test "$(git hash-object evals/datasets/benchmark-seed/questions.jsonl)" = 2ca0cadea22cc54f2dd004e8fc60127e78518ec4
test "$(git hash-object docs/research/ontology/README.md)" = 7804a7246cc43920723b9d16ac4d0bbb1471259f
test "$(git hash-object docs/research/ontology/saas-disclosure-survey.md)" = 6c98920e4350ee394d1c19023dea048820233819
```

Run the benchmark validator embedded in `evals/datasets/benchmark-seed/README.md`, then add/check these invariants in the PR test:

```text
65 unique IDs
10 exact canonical categories, each >= 5
59 answerable / 6 unanswerable
42 numeric-string / 17 text answers
73 evidence records / 24 distinct accessions
16 issuers; every ticker/CIK equals current issuer-cohort.json
all as_of values parse as timezone-aware timestamps
every evidence accession is included in documents_reviewed
every evidence public-availability timestamp <= as_of
```

Finally run the repository's normal gate from the repository root:

```bash
make ci
```

SEC/source verification is a separate online gate and must use the repository-configured SEC identity/rate limiter without emitting contact details or raw fetched documents into logs.
