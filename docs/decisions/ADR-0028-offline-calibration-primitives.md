# ADR-0028: Offline extraction calibration preparation

Status: Accepted for bounded implementation under the owner's approved completion plan and parallel implementation handoff request

Date: 2026-09-16

Issues: #333, #336, #337; parent #62. Parent milestone/live dependencies remain unchanged.

Authorize two independent standard-library-only offline primitives: a strict dataset/provenance/split validator and deterministic weighted pool-adjacent-violators isotonic-v1 fit/predict/evaluate. The exact interchange, support, numerical rules, resource bounds and errors are frozen in `docs/research/offline-calibration-contract.md`. No common mutable module or new dependency is needed.

Choose exact-count weighted PAV rather than a new statistical dependency; explicit tie/prediction/rounding rules make tests and artifacts reproducible. Choose declared issuer/time-disjoint train/calibration/evaluation splits rather than random allocation. Fit only calibration samples; evaluation never refits. Per-stratum calibration and evaluation each require at least100 labels with20 of each outcome for the offline readiness report. Train support is reported, not a new release requirement. No strata are silently pooled or dropped.

Synthetic fixtures prove mechanics only. Declared human reviewer IDs do not prove actual adjudication; signed human review/provenance and live empirical gates remain external acceptance. Existing runtime NULL confidence remains unchanged, and no new score producer, autoapproval, calibrator persistence, policy API, provider call or runtime integration is authorized by these children.

External agents exclusively own the registered files on separate branches. Both can work concurrently using the same immutable contract pin. Integration lead reviews evidence and runs full required CI before merge. #62 and canonical task completion remain open.
