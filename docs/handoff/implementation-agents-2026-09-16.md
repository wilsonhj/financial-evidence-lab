# Ready external implementation assignments — Financial Evidence Lab

Prepared September 16, 2026 for the owner's request to implement in parallel.
Repository: https://github.com/wilsonhj/financial-evidence-lab

**These two cards authorize implementation, not only research/review.** They replace
the earlier research-only cards only for issues #336 and #337. Both are reserved
for external owners; the local team will not implement their files. Each can run
independently against the same frozen contract without waiting for the other.

## Immutable starting point and contract

Base and contract commit: `c9debdcbd9fcb44a623dc3a7a7278cfd97d6260e`.
Fetch branch `agent/public-guard-control` to obtain that commit, then check out the
exact pin. Do not use the moving branch tip as your specification. This commit
contains accepted ADR-0028, the frozen offline contract and exact path registration;
application code at this pin is the already merged provider/cipher baseline.

Read, in order: `AGENTS.md`, `.specify/memory/constitution.md`,
`specs/001-financial-evidence-lab/{spec,plan,tasks}.md`,
`docs/handoff/{README.md,workstreams.yaml}`, `docs/decisions/ADR-0028-offline-calibration-primitives.md`,
and **`docs/research/offline-calibration-contract.md`**. The contract, not this
shortened card, defines exact types, algorithms, error codes, bounds and metrics.
Do not edit any of those read-only files.

Example in your own clone (never switch/reset another person's checkout):

```bash
git fetch origin agent/public-guard-control
git cat-file -e c9debdcbd9fcb44a623dc3a7a7278cfd97d6260e^{commit}
git worktree add -b agent/offline-calibration-dataset ../fel-cal-dataset c9debdcbd9fcb44a623dc3a7a7278cfd97d6260e
```

For card B use its different branch and a separate worktree. One named owner per
card. At most three specialists plus the integration lead may be active across
the coordinated team; start these two together after at least one local guard
implementer has finished if both API/web guard owners are still active. Never
start duplicate owners merely because an issue remains open.

## A — #336: strict dataset validator and support report

Issue: https://github.com/wilsonhj/financial-evidence-lab/issues/336
Branch: `agent/offline-calibration-dataset`

Exclusive write paths:

- `evals/harness/calibration_dataset.py`
- `evals/tests/test_calibration_dataset.py`
- `evals/datasets/calibration/README.md`

Implement the frozen `extraction-calibration-dataset/v1` reader, canonical bytes/hash
and support report. Public APIs: `load_dataset`, `canonical_dataset_bytes`,
`dataset_digest`, `support_report`; safe `CalibrationDatasetError` codes.

Enforce exact schemas/types, strict canonical identities/scores, bounded JSON,
immutable manifest pins, chronological publication/as-of/adjudication, pairwise
issuer/time splits and proposal/source isolation. Canonicalization must be stable
under key/record permutations. Report missing stratum/split cells as zero. Readiness
requires calibration and evaluation support for every observed stratum; train
support is reported, not a new release gate. Valid insufficient data is a report,
not an excuse to invent labels or drop strata.

Write failing tests first for duplicates, bool/float/nonfinite values, malformed
UTC dates, split leakage, inconsistent proposal identities, limits, canonical
hashes and exact support boundaries. Generate synthetic fixtures in your owned
module; do not copy private records or call synthetic labels human-adjudicated.

## B — #337: deterministic weighted PAV calibration

Issue: https://github.com/wilsonhj/financial-evidence-lab/issues/337
Branch: `agent/offline-isotonic-calibrator`

Exclusive write paths:

- `workers/src/fel_workers/extraction/isotonic.py`
- `workers/tests/extraction/test_isotonic.py`
- `workers/src/fel_workers/extraction/ISOTONIC.md`

Implement pure `fit`, `predict`, `evaluate` and safe `CalibrationError`. Consume
one-stratum score/outcome tuples directly; **do not import card A**. Group score
ties, compare/merge weighted block means using exact integer ratios, preserve
frozen left-step/clamping behavior, validate artifacts, and isolate decimal
rounding from ambient context. Implement exact held-out Brier/ECE outputs and
insufficient-data states. Evaluation never refits. No model training or inference.

Write failing tests first for weighted pooling/ties, known rational oracles,
permutation/monotonicity, endpoint/gap predictions, support thresholds, hostile
artifacts, decimal context and metric/bin edges. Respect the contract's 16-container
limit where applicable, exact output shapes and error/status precedence.

## Shared prohibitions and acceptance

Use only existing standard-library facilities and the locked test toolchain. No
new dependency, schema, shared helper, conftest, API, migration, runtime registration,
worker-stage import, policy threshold or persistence edit. Do not write to another
card's paths. If a missing seam is essential, return its exact proposed contract
to the lead; continue independent owned work without widening the allowlist.

Existing runtime confidence remains NULL where unscored. Returning zero for an
insufficient offline artifact does not authorize writing scores to proposals.
No autoapproval, label adjudication, provider call, credential access, model
promotion, deployment, release claim or canonical checkbox change. #62 retains
its milestone/live/human gates. Public signup/BYOK and deployment guard work are
owned locally under #333–#335 and are outside these cards.

In an isolated environment, use the repo-pinned Python version and hash-locked
requirements; do not modify locks. Example commands (substitute card B's paths):

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python -m pytest evals/tests/test_calibration_dataset.py -o addopts='--import-mode=importlib' -q
python -m ruff check evals/harness/calibration_dataset.py evals/tests/test_calibration_dataset.py
python -m black --check evals/harness/calibration_dataset.py evals/tests/test_calibration_dataset.py
python -m mypy evals/harness/calibration_dataset.py
git diff --check
```

No live DB or external API is needed for either package. Do not run against an
inherited hosted DSN. A skipped required test is not a passing test. Record real
command output and exit status; distinguish tests not run from passes.

## Return and integration protocol

Commit only your three allowed files. Push the assigned branch and open a draft
PR if your environment has repository write authorization; otherwise
return a `git format-patch` file from the pinned base. If integration PR #338 is
still open, use `agent/public-guard-control` as the draft PR base so the review
shows only your three files. After #338 merges, the lead integrates current main
and retargets the draft to main. If #338 is already merged, target main directly.
Do not merge, deploy, close
issues or post unrelated comments/messages. Include:

1. Issue/card and exact base/contract/head SHAs; changed-file list.
2. One-paragraph resulting behavior and any unresolved limitation.
3. Failing-before/passing-after evidence plus exact test/static-check commands.
4. Deterministic test oracles and any contract ambiguity encountered.
5. Patch or PR link. No secrets, private records or raw provider responses.

The integration lead reviews the exact commit, checks ownership/contract compliance,
rebases or integrates against current main, and runs required CI. Later single-owner
orchestration will combine the primitives; that work is not part of either card.
