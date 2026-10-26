# Unit comparison policy deployment

<details>
<summary>Relevant source files</summary>

- [packages/ontology/fel_ontology/units.py](../../packages/ontology/fel_ontology/units.py) — `unit-comparison/v1` canonicalization
- [packages/ontology/fel_ontology/data/currency-codes.json](../../packages/ontology/fel_ontology/data/currency-codes.json) — pinned ISO 4217 currency vocabulary
- [workers/src/fel_workers/extraction/types.py](../../workers/src/fel_workers/extraction/types.py) — workflow and validator version pins
- [workers/src/fel_workers/extraction/validate/pipeline.py](../../workers/src/fel_workers/extraction/validate/pipeline.py) — validation summaries with unit-policy provenance
- [workers/src/fel_workers/extraction/validate/duplicates.py](../../workers/src/fel_workers/extraction/validate/duplicates.py) — policy-namespaced conflict keys

</details>

Source references verified against commit `437ce55`.

The current producer target is `extraction-workflow/v3`; follow the
[signed guidance range rollout](guidance-range-policy-migration.md). The v2
instructions below describe the original unit-policy release and remain relevant
only to its pinned historical runs. `unit-comparison/v1` is unchanged.

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

## Related pages

- [Signed guidance range policy deployment](guidance-range-policy-migration.md)
- [Extraction worker runbook](extraction-worker.md)
- [Ontology](../../packages/ontology/README.md)
- [ADR-0019: unit comparison policy](../decisions/ADR-0019-unit-comparison-policy.md)
