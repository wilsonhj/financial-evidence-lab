# Unit comparison policy deployment

ADR-0019 introduces `unit-comparison/v1`, `validate/v2` and
`extraction-workflow/v2`. The normalizer stays `normalize/v1`; normalize and
validate checkpoint inputs explicitly include their component and policy pins.
Validation summaries record validator and unit-policy provenance.

Deploy the new worker for new v2 runs. Producers must use the worker's supported
workflow version when creating a run. Existing persisted run pins are immutable:
do not repin a v1 run. To finish an interrupted v1 run, use its pinned old worker
release; alternatively request an explicit new v2 extraction run. New code rejects
v1 before checkpoint recovery or provider dispatch, including runs with valid
succeeded checkpoints. Historical completed outputs remain readable.

The checked-in currency vocabulary is SIX ISO 4217 List One (source publication,
retrieval date and SHA-256 in `fel_ontology/data/currency-codes.json`). Updating
that vocabulary changes comparison semantics and requires a reviewed policy and
workflow rollout; do not refresh it automatically at runtime.

Source unit spelling and proposal-ID calculation are unchanged. Comparison aliases
do not convert currencies, rates, ratios or amounts. Known currency numerators
fold ASCII case while denominators retain their exact spelling. Currency fields
still require uppercase ASCII alpha-3 syntax; units do not infer missing currency.

All new conflict keys include the policy namespace. Old conflict keys, membership,
resolution and audit history remain untouched and coexist with new groups. An old
adjudication does not resolve a new-policy group: reviewers must review it. Replay
within the same policy remains idempotent for open groups; the existing terminal
group guard still rejects attaching unreviewed proposals to an adjudicated group.

No database migration, historical rewrite, automatic re-extraction or automatic
run repinning is part of this deployment.
