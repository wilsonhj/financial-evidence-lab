# Offline `isotonic-v1` calibration primitive

Preparatory child of #62, reserved to issue #337. This module is a pure
standard-library weighted pool-adjacent-violators fitter. It does not import
the dataset validator, worker stages, providers, or persistence.

## Public API

- `fit(samples)` — one stratum of canonical score/outcome tuples
- `predict(artifact, score)` — left-step / endpoint-clamped probability
- `evaluate(artifact, samples)` — held-out Brier and 10-bin ECE; never refits

Returned probabilities and metrics use an isolated Decimal context
(`prec=50`, `ROUND_HALF_EVEN`) quantized to 12 places. Ambient Decimal
context must not affect results. Integer cross-products decide PAV merges;
ties are grouped by exact score before pooling; adjacent equal means are
coalesced.

Scores use canonical spelling: `0`, `1`, or `0.` followed by 1-12 digits
with a nonzero last digit (for example `0.1` is accepted but `0.10`,
`0.0`, and `0.100000000000` are rejected as `invalid_sample`). Emitted
12-place strings such as `0.100000000000` must not be fed back as scores.

## Insufficient support

Per-stratum calibration support is at least 100 rows with 20 of each outcome.
Below that, `fit` returns `status=insufficient_data` and empty blocks.
`predict` on that artifact returns unquantized `Decimal("0")` (formats as
`"0"`, distinct string from fitted `"0.000000000000"` though `==`-equal).
This is attempted but insufficient scoring, distinct from historical runtime
`NULL` confidence, and must not be written onto existing proposals. Callers
must branch on `status`, never on the predicted value.

`evaluate` validates the artifact and the held-out rows first. If the artifact
is insufficient, status is `insufficient_calibration` even when evaluation
rows would have been enough. Otherwise insufficient held-out rows yield
`insufficient_evaluation`. Metrics are null in both cases; they are never
fabricated as zero.

## What this package does not do

- Call models, choose a raw-score producer, or register a runtime calibrator
- Persist artifacts, change review policy, or auto-approve proposals
- Prove human adjudication or live accuracy
- Close #62 or any canonical Spec Kit task
