# Offline extraction calibration dataset (`extraction-calibration-dataset/v1`)

Preparatory child of #62, reserved to issue #336. This directory documents the
offline interchange only. It does not store private labels, source filings, or
provider output.

## Scope

`evals/harness/calibration_dataset.py` is a standard-library validator for the
frozen `extraction-calibration-dataset/v1` bytes. Public functions:

- `load_dataset`
- `canonical_dataset_bytes`
- `dataset_digest`
- `support_report`

Every entry validates exact schema, identities, chronology, split isolation,
size bounds, and canonical spelling. Insufficient but well-formed support is a
report, not an exception and not a reason to invent labels.

Synthetic fixtures used by `evals/tests/test_calibration_dataset.py` are
generated in that test module. They are conspicuously `evidence_kind=synthetic`.
They are not human adjudication, live calibration, or release evidence. A
syntactically `adjudicated` fixture still does not prove that a qualified
reviewer labeled the rows.

## What this package does not do

- Call providers, databases, or worker stages
- Persist calibrators or write proposal confidence
- Choose a score producer or policy threshold
- Close #62 or any canonical Spec Kit task
- Treat SHA-256 pins as proof that the referenced source bytes were fetched

The later integration owner consumes a validated split here and fits
`isotonic-v1` elsewhere. Train support is reported and does not gate the
offline `ready` flag; calibration and evaluation support do.
