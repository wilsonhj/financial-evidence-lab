# Ontology (`packages/ontology`)

<details>
<summary>Relevant source files</summary>

- [fel_ontology/data/saas-metrics.v1.json](fel_ontology/data/saas-metrics.v1.json) — the `saas-metrics/v1` ontology: 9 families, 14 metrics
- [fel_ontology/models.py](fel_ontology/models.py) — `Family`, `MetricDef`, `OntologyDocument` dataclasses and their literal vocabularies
- [fel_ontology/loader.py](fel_ontology/loader.py) — `load_saas_metrics`, strict validation, `ontology_content_hash`
- [fel_ontology/comparability.py](fel_ontology/comparability.py) — `build_comparability_key`, `metrics_comparable`
- [fel_ontology/units.py](fel_ontology/units.py) — `unit-comparison/v1` unit canonicalization (ADR-0019)
- [fel_ontology/data/currency-codes.json](fel_ontology/data/currency-codes.json) — pinned ISO 4217 List One codes with source and SHA-256
- [pyproject.toml](pyproject.toml) — package metadata; ships `data/*.json`
- [tests/](tests/) — loader, comparability, unit and definition-conflict tests

</details>

Source references verified against commit `437ce55`.

`fel-ontology` is the machine-readable B2B SaaS metrics ontology used by the
extraction runtime. It defines which metrics exist (ARR, MRR, NRR, GRR,
customer counts, seats, bookings, billings, RPO, cRPO, deferred revenue,
subscription and services gross margin), the qualifiers each one requires, and
the fields that decide whether two extracted values are comparable. It has no
runtime dependencies. This page is for developers changing metric definitions
or the code that consumes them.

The ontology encodes metric IDs and qualifier/comparability keys only. The
disclosure survey it was informed by is a research draft and is not acceptance
evidence; see the `limitations` field in the JSON and
[the ontology research notes](../../docs/research/ontology/README.md).

## Public API

Exported from `fel_ontology`:

| Name                                                 | Purpose                                                                |
| ---------------------------------------------------- | ---------------------------------------------------------------------- |
| `load_saas_metrics(*, path=None)`                    | Load and validate the packaged ontology (or a file at `path`)          |
| `ontology_content_hash(raw)`                         | `sha256:<hex>` digest of the raw ontology bytes                        |
| `build_comparability_key(metric, qualifiers)`        | Deterministic key from the metric's `comparability_key_fields`         |
| `metrics_comparable(left, lq, right, rq)`            | True only when both comparability keys are identical                   |
| `Family`, `MetricDef`, `OntologyDocument`            | Typed, frozen views of the JSON document                               |
| `OntologyLoadError`                                  | Raised for any invalid document                                        |

`fel_ontology.units` is imported directly: `canonical_unit`,
`is_monetary_unit`, and `UNIT_POLICY_VERSION = "unit-comparison/v1"`.

## Validation rules

The loader fails closed rather than loading a partial document:

- `schema_version` must be `saas-metrics/v1` and `ontology_id` `saas-metrics`;
- the family count and the set of metric IDs are fixed in `loader.py`;
- `kind`, `value_type`, and `period_semantics` must be members of the
  `Literal` vocabularies in `models.py`;
- list fields such as `comparability_key_fields` must be non-empty, because an
  empty key would make every fact comparable to every other.

`build_comparability_key` raises `KeyError` when a required qualifier is
missing or blank, so an incomplete extraction is never treated as comparable.
Aliases help classification but never merge two issuers' definitions into one
key.

## Units

`canonical_unit` folds only an explicit set of ASCII aliases (for example `%`
and `pct` to `percent`, `pp` to `percentage_points`) and upper-cases known
ISO 4217 currency numerators. Unknown issuer units are returned unchanged. It
never converts currencies, rates, or amounts. Changing the currency vocabulary
changes comparison semantics and requires a reviewed rollout; see the
[unit policy runbook](../../docs/runbooks/unit-policy-migration.md).

## Consumers

- API extraction validation: `apps/api/app/extraction/runs.py`,
  `validation.py`, `validation_peers.py`.
- Worker extraction: `workers/src/fel_workers/extraction/workflow.py`,
  `workflow_context.py`, `roles/base.py`, `normalize/currency.py`, and the
  validators under `validate/`.

Because the worker imports this package at startup, `packages/ontology` must be
on `PYTHONPATH` for both services.

## Test

```sh
.venv/bin/pytest packages/ontology/tests
```

## Related pages

- [System design: ontology](../../docs/architecture/system-design.md#ontology-packagesontology)
- [Workers](../../workers/README.md)
- [Unit comparison policy deployment](../../docs/runbooks/unit-policy-migration.md)
- [Signed guidance range policy deployment](../../docs/runbooks/guidance-range-policy-migration.md)
- [Ontology research notes](../../docs/research/ontology/README.md)
- [ADR-0019: unit comparison policy](../../docs/decisions/ADR-0019-unit-comparison-policy.md)
