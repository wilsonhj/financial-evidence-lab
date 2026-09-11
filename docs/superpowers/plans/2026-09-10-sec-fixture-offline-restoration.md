# SEC Historical Baseline Offline Restoration Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` for this bounded plan; root owns dispatch, independent review, recorded approval and merge under the owner's instruction. Implementation requires the matching ready workstream.

**Goal:** Recover the exact historical 60-record manifest with its source license and a reproducible structural check, explicitly preserving its unverified status.

**Architecture:** Restore individual Git blobs from the final historical head, never merge the obsolete branch. One standard-library validator checks recorded structure and recovery fingerprints; it has no fetcher or feature detector and cannot certify full acceptance. Rewrite the two documentation files to remove unsupported present-tense claims and the historical personal SEC contact.

**Tech Stack:** Python 3.11 standard library (`argparse`, `collections`, `datetime`, `hashlib`, `json`, `pathlib`, `re`, `unittest`); existing locked Black/Ruff/mypy/Bandit. No dependency/configuration changes.

**Spec:** issue #81 and the recovery findings in `docs/handoff/execution-2026-09-09.md`; final source `d8fd80ea3ed0f09d981b5a072e18a099f3aedd51`; current-main source examined at `3df6dec79fbb6e5397417e06ed0f388985317aa3`. The broader design's network verification and supplemental work are deliberately deferred to a separate dispatch.

## Constraints and feasibility

Everything in the future PR must remain under `evals/datasets/sec-fixtures/**`. Root `LICENSE`/`NOTICE`, canonical cohort, CI, root configs/locks, workers, shared handoff and API/contracts are untouched. Create a fresh worktree from the then-current main only after root registers its issue/branch. Do not alter the dirty primary checkout.

This checkpoint requires no network, no SEC identity, and no response to the pending `FEL_SEC_USER_AGENT` question. All needed source blobs exist in local Git. Do not read, print, copy, adopt or validate the value of that environment variable; mention its name only. Do not fetch SEC filings or submissions, discover supplemental issuers, add excerpts, implement detectors, or claim the eight-feature gate. Existing dependencies suffice.

The original issue acceptance remains open: this PR restores inspectable historical inputs, not a byte-verified parser baseline. The required eight-feature gate remains eight; structural success does not satisfy it. Root must obtain the user's requested review/test/approval before merge, even if all code checks pass.

## Independently checked source evidence

Inspected local Git objects in `/Users/hirokazu/Developer_Projects/financial-evidence-lab`; no fetch, checkout, repository mutation or SEC request was performed for this design. The historical contact lines were suppressed before README output.

| Material | Source / fingerprint |
| --- | --- |
| Manifest | `d8fd80e:evals/datasets/sec-fixtures/manifest.jsonl`, blob `5a2662157357460f76c556507f50d5eb7b5132cb`, 33,123 bytes |
| Exact manifest SHA-256 | `945d36c0c95993b03b54bd4a1af96b7d6c9412a74420cccef39b9687b2d897cc` |
| Historical README | blob `07f2eab0901902e1a77a54bd0713911dfee842dd`, 10,033 bytes; replacement is intentional |
| Historical excerpt README | blob `09117b27ba02fba2e83480fd2441c0ba50ca24b1`, 589 bytes; replacement is intentional |
| Source root MIT license | `d8fd80e:LICENSE`; SHA-256 `9df2530031b509fd7af008447f39b631abb2058c31cfe2febb49a3de3cea83a9` |
| Canonical cohort, read only | `evals/datasets/issuer-cohort.json`; SHA-256 `3fda084f60f4fd00225d36e0e6233ac03d0f2ff4420cad1b9d2ef95cf72e4b4c` |

Recounted facts about the stored data: 60 rows; 60 unique IDs/accessions/URLs/hash strings; 20 cohort CIK/ticker pairs; sequential IDs FX-0001 through FX-0060. All stored archive URLs equal the path built from their recorded CIK, accession and primary document. Twenty-one accession prefixes differ from issuer CIK; this is legal filing-agent behavior, so **do not require accession prefix == issuer CIK**.

Stored forms: 20 10-K, 30 10-Q, six 10-K/A, four 10-Q/A. Stored feature assertions: unusual_scale_markers52, ixbrl_continuation45, ixbrl_dimensional_facts43, legacy_html_no_ixbrl14, pre_2018_formatting14, amended_filing10, multi_currency2. These are seven distinct recorded labels, with zero freshly verified feature types. `/A` labels and pre-2018 labels are internally consistent with recorded form/date; this does not establish SEC metadata provenance.

## Exact file budget

| Path under `evals/datasets/sec-fixtures/` | Action / responsibility | Target lines |
| --- | --- | ---: |
| `manifest.jsonl` | Restore exact final blob; never reserialize or reformat | 60 |
| `README.md` | Concise replacement: provisional status, recovery hashes, structural command, evidence debt, sanitization, licensing | 85 |
| `excerpts/README.md` | State no recovered excerpt bytes; absence of files is not evidence that no filing qualifies | 12 |
| `SOURCE-LICENSE.txt` | Exact historical MIT license bytes, including original copyright and permission notice | 22 |
| `validate.py` | Offline structural validator and CLI | 180 |
| `tests/test_validate.py` | Standard-library tests, temporary mutated copies only | 190 |
| Total target | Includes restored data and notices; aim below600 review-bearing lines | 549 |

No `fetch.py`, `features.py`, verification receipts, supplemental manifest, generated coverage/report artifact, full filings, copied historical README, or new workflow belongs in this PR. Test files live under `tests/` to follow existing coverage omission conventions, without changing coverage settings.

## Validator contract

Two callable boundaries suffice:

```python
def validate_manifest(data: bytes, cohort_data: bytes) -> list[str]:
    """Return deterministic structural/recovery error codes; never feature verification."""


def main(argv: list[str] | None = None) -> int:
    """Read the fixed adjacent manifest and canonical cohort, print a bounded report."""
```

Use fixed paths relative to `__file__`, not the caller's working directory. No CLI manifest override, cache option, online option, implicit environment configuration or automatic golden regeneration is needed. Tests call the pure byte-input function with synthetic mutations of recovered data; no production mutation escape hatch is necessary.

The CLI accepts **only `--structural-only`** (plus argparse help). It always emits a plainly scoped report with `scope="historical_structure"`, `acceptance_passed=false`, `verified_feature_count=0`, and counts labeled `historical_feature_assertions`. Suggested exit semantics:

- `0`: explicit `--structural-only`, with all recovery/structural checks passing.
- `1`: read/UTF-8/JSON/schema/identity/fingerprint failure. Report field/error code and row number, not raw contents.
- `2`: structure passes but default full acceptance is unavailable. Explain missing fetched bytes, receipts, feature witnesses, representative excerpts and amendment-original provenance. Even if someone places arbitrary cache files nearby, this validator has no acceptance implementation and never upgrades the result.

A default invocation therefore fails closed instead of printing an ambiguous `OK` that might be used as a full gate. `--structural-only` is an explicit limited-purpose success; its JSON still says acceptance is false. No threshold of seven is implemented. No `--require-bytes` flag should imply an unfinished verifier exists.

Checks, in stable order:

1. Compare raw manifest and cohort SHA-256 with the constants above. Exact restoration means even whitespace drift is a recovery error. Parse despite a fingerprint error where safe so mutation tests can also exercise concrete diagnostics.
2. Strict UTF-8, nonempty JSONL records, 60 rows, object per row; reject duplicate JSON keys using `object_pairs_hook`. JSON booleans cannot satisfy numeric checks. Reject missing/extra row keys and nested issuer keys.
3. Exact historical row keys: `id`, `issuer`, `form`, `accession`, `filed_at`, `primary_document`, `url`, `sha256`, `why_selected`, `stress_features`. Issuer keys are `ticker`, `cik`. All scalar values must be nonempty strings; features a nonempty list of unique strings.
4. ID `FX-[0-9]{4}` and exact sequence0001–0060; CIK ten digits; accession `[0-9]{10}-[0-9]{2}-[0-9]{6}`; lowercase64hex hash; real date exactly `YYYY-MM-DD`; historical forms `10-K`, `10-Q`, `10-K/A`, `10-Q/A`. No supplemental fields are accepted.
5. Read cohort issuer CIK/ticker pairs from the canonical file; require its documented20 unique pairs and all20 represented. Do not duplicate the issuer table in code. Reject a non-cohort CIK or mismatched ticker. Exact cohort digest makes a silently substituted cohort fail.
6. Primary document must be a single basename matching `[A-Za-z0-9][A-Za-z0-9._-]*`, without `/`, backslash, percent escape, query, fragment or dot-segment. URL must exactly equal `https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_without_dashes}/{primary_document}`. This verifies recorded association only, not SEC ownership or a successful HTTP response.
7. Enforce global unique IDs, accessions, URLs and hash strings. Distinct hash strings are historical uniqueness evidence, not document byte correctness.
8. Recognize exactly these eleven historical tag names: `ixbrl_continuation`, `ixbrl_dimensional_facts`, `nested_tables`, `rotated_tables`, `unusual_scale_markers`, `multi_currency`, `legacy_html_no_ixbrl`, `amended_filing`, `restatement_nonreliance`, `fiscal_year_transition`, `pre_2018_formatting`. Count stored labels only. Reject an unknown tag or duplicate label; do not implement feature detectors. Check `amended_filing` iff stored form ends `/A`, and `pre_2018_formatting` iff stored date precedes2018-01-01, describing those as internal metadata consistency. Do not guess originals or treat these checks as verified facts.

Keep data-derived diagnostic output to row index and field names. Neither exception rendering nor tests should copy the removed personal contact. No general schema framework, network abstraction, relationship inference or feature registry is needed.

## Task1: Restore and relabel the historical baseline

- [ ] In the root-registered fresh worktree, write the manifest using Git bytes, not a shell text transform:

```bash
mkdir -p evals/datasets/sec-fixtures/excerpts
git show d8fd80ea3ed0f09d981b5a072e18a099f3aedd51:evals/datasets/sec-fixtures/manifest.jsonl > evals/datasets/sec-fixtures/manifest.jsonl
git show d8fd80ea3ed0f09d981b5a072e18a099f3aedd51:LICENSE > evals/datasets/sec-fixtures/SOURCE-LICENSE.txt
```

- [ ] Replace README from scratch using the independently checked facts above. Title it “Historical SEC fixture manifest — unverified recovery”. Preserve source commit/blob/hash references. Describe historical authors' byte/coverage claims as unverified; avoid copying their claims of complete histories, clean cohort, verified absences, 60 verified entries or current egress. Do not reproduce the old inline `>=7` gate.
- [ ] Include this sanitization disclosure: “The historical README contained a personal SEC contact identity. This recovery omits that identity and documents only the existing FEL_SEC_USER_AGENT setting name. No contact was adopted and no SEC requests were made.” The new README should contain no literal email address or personal request header.
- [ ] State that the source material's MIT notice is preserved in SOURCE-LICENSE.txt, while current root license files are untouched. Do not imply the source notice licenses issuer filing contents. The license's original copyright notice is preserved verbatim; it is distinct from the omitted SEC request identity.
- [ ] Replace excerpts README: no excerpt bytes recovered; representative excerpts and their provenance remain required in the later evidence acceptance work. Do not attribute emptiness to proven absence of nested tables.
- [ ] Verify exact manifest/license hashes and path-only diff, then commit the bounded recovery. No new baseline bytes or tags may be invented to satisfy checks.

## Task2: Structural validation with explicit acceptance failure

- [ ] Write RED tests for the two entry points and CLI semantics before implementation. Load `validate.py` using `importlib.util.spec_from_file_location` because the dataset directory has a hyphen. Standard-library unittest avoids dependencies.
- [ ] Test the actual restored manifest/cohort return no structural errors, exact fingerprint preservation, and the CLI's explicit structural success versus default exit2. Assert every successful structural report keeps acceptance false and verified count zero.
- [ ] Use `subTest` mutations for missing/unknown keys, duplicate JSON keys, wrong scalar/list types, duplicate feature, unknown tag, malformed/invalid dates, malformed CIK/accession/hash, duplicate identity fields, foreign CIK and wrong ticker, unsafe document basename, non-SEC/query/fragment URL and swapped accession path. Assert the relevant structural error code, as well as fingerprint failure where applicable.
- [ ] Test legal filing-agent prefix mismatch, all20 cohort members, `/A` and pre-2018 internal consistency; assert seven stored labels never become an eight-feature success. Do not mutate the checked-in golden file. Temporary synthetic rows are test inputs only.
- [ ] Test missing files/read failure using temporary directory setup or patched reads; no external services or credentials. Test `main(["--structural-only"])` and `main([])` with captured output, plus one real subprocess CLI smoke. No bare `assert` in production validator; return errors explicitly so optimized Python does not disable validation.
- [ ] Implement only the checks above, run focused checks, inspect all branches for misleading success, and commit. Do not broaden into byte checking when full acceptance deliberately returns2.

## Exact planned commands and review evidence

These are commands for the later implementation, not tests already run in this design task. Use the repository's locked Python3.11 environment, not whichever `python3` happens to be on PATH.

```bash
python -m unittest discover -s evals/datasets/sec-fixtures/tests -p 'test_*.py' -v
python evals/datasets/sec-fixtures/validate.py --structural-only
python evals/datasets/sec-fixtures/validate.py
black --check evals/datasets/sec-fixtures
ruff check evals/datasets/sec-fixtures
mypy evals/datasets/sec-fixtures/validate.py
bandit -q -r evals/datasets/sec-fixtures -c pyproject.toml
git diff --check
git diff --numstat main -- evals/datasets/sec-fixtures
```

The third command must exit2, with the explicit missing-acceptance report; capture and assert that exit in the CLI test rather than masking it with `|| true`. A failed full gate is expected evidence of honest scope, not a PR implementation failure.

Current CI's pytest `testpaths` excludes `evals/datasets/sec-fixtures/tests`; therefore its generic green pytest check will **not** prove the new tests ran. Run the exact unittest command on the final PR head and record test count/output in the PR. Do not edit shared CI configuration to conceal that scope limitation. Existing root CI still runs formatting/lint/security over `evals`; preserve the88.41% Python coverage floor and all current required checks. Inspect actual final coverage rather than assuming this new path is or is not counted.

Independent review must verify: exact final-source manifest hash, exact MIT notice, README sanitization without exposing the removed value, no misleading feature/absence/history claims, structurally correct record/URL checks, no false CIK-prefix restriction, explicit default acceptance failure, and allowed-path/line-budget compliance. Root shares the PR link, records independent review and integration-lead approval, and merges only after exact-head tests and required CI pass.

## Later work stays blocked separately

Fresh byte/hash verification, eight genuinely witnessed features, representative excerpts, ten amendment-original relationships, and three–six supplemental non-cohort issuers remain outside this PR. Their SEC network phase still requires a current approved FEL_SEC_USER_AGENT and bounded request authorization. Restoring these local historical inputs is independently feasible today and neither answers nor bypasses that outstanding network identity question. Do not close #81 or mark canonical acceptance complete for this checkpoint.
