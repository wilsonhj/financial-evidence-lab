# M3 Agentic Extraction — Data Model

All authoritative identifiers are UUIDs unless noted. Every tenant table has `org_id`, RLS, indexes beginning with `org_id`, and worker-side ownership validation. Public source evidence remains read-only. All timestamps are `timestamptz`; all authoritative numbers are decimal strings or PostgreSQL `numeric`.

## Tables

### `extraction_policies`

One versioned policy per organization: `id`, `org_id`, `version`, `record_threshold numeric(4,3)=0.850`, `field_threshold numeric(4,3)=0.800`, `max_calls=10`, `max_input_tokens=100000`, `max_output_tokens=20000`, `max_cost_usd numeric(12,6)=2.0`, `max_wall_seconds=600`, `created_by`, `created_at`, `supersedes_id`. Policy rows are immutable; unique `(org_id, version)`. Only owner API creates the next version and records an audit event.

### `extraction_runs`

`id`, `org_id`, `workspace_id`, `entity_id`, `status`, `modes` (array of `kpi`|`guidance`|`revenue_driver`), `as_of`, `corpus_version_id`, `ontology_version`, `workflow_version`, `provider`, `model`, `policy_id`, `input_manifest jsonb`, `input_hash`, `idempotency_key`, budget/cost counters, `parent_run_id`, `version`, `error jsonb`, `created_by`, `created_at`, `started_at`, `finished_at`.

Closed status: `queued`, `running`, `waiting_review`, `succeeded`, `failed`, `cancelled`. Unique `(org_id, workspace_id, idempotency_key)`. `input_manifest` is canonical JSON containing sorted claim/span IDs and versions; never source text.

### `extraction_run_steps`

`id`, `org_id`, `run_id`, `step_name`, `attempt`, `status`, `input_hash`, `output_hash`, `workflow_version`, `schema_version`, `prompt_version`, `provider_response_id`, token/cost fields, redacted `error`, `started_at`, `finished_at`. Closed status: `pending`, `running`, `succeeded`, `failed`, `skipped`, `cancelled`. Unique `(run_id, step_name, attempt)` and unique successful `(run_id, step_name, input_hash, workflow_version)`.

### `extraction_run_events`

`id bigint identity`, `org_id`, `run_id`, `event_type`, `payload jsonb`, `created_at`. Append-only; `(org_id, run_id, id)` index. Payload contains IDs/counts/status, never evidence or prompt text. SSE `id:` equals table ID.

### `extraction_proposals`

`id`, `org_id`, `workspace_id`, `run_id`, `kind`, `metric_id`, `payload jsonb`, `raw_payload_hash`, `definition_hash`, `comparability_key jsonb`, `record_confidence numeric(4,3)`, `field_confidences jsonb`, `validation_summary jsonb`, `state`, `review_priority`, `version`, `created_at`. Kind: `kpi`, `guidance`, `revenue_driver`. State: `proposed`, `needs_review`, `accepted`, `rejected`, `superseded`. A trigger forbids changing `payload`, hashes, or run after insert; state/version advances only in review transactions.

### `extraction_proposal_evidence`

`org_id`, `proposal_id`, `source_span_id`, `document_version_id`, `role`, `citation_status`, `ordinal`, primary key `(proposal_id, source_span_id, role)`. Role: `supports`, `definition`, `conflicts`, `derivation_input`. Citation status: `verified`, `partial`, `contradictory`, `invalid`. Insert checks the span's document version, pinned corpus, and cutoff in worker/application code; acceptance repeats it in SQL.

### `extraction_conflicts`

`id`, `org_id`, `workspace_id`, `conflict_key`, `reason_codes text[]`, `status`, `resolved_by`, `resolved_at`, `resolution_note`, `created_at`. Status: `open`, `resolved`, `superseded`. Join table `extraction_conflict_members(conflict_id, proposal_id)`; at least two members enforced by transaction/service test.

### `extraction_reviews`

Append-only: `id`, `org_id`, `workspace_id`, `action`, `actor_user_id`, `reason`, `request_id`, `idempotency_key`, `expected_versions jsonb`, `input_ids uuid[]`, `patch jsonb`, `result_ids uuid[]`, `created_at`. Action: `accept`, `edit`, `reject`, `merge`, `rerun`. Unique `(org_id, idempotency_key, action)`. Review payload cannot contain raw source text.

### `approved_extraction_records`

Stable logical identity: `id`, `org_id`, `workspace_id`, `kind`, `metric_id`, `entity_id`, `current_version_id`, `version`, `created_at`. Unique canonical key may be used only when ontology comparability fields are fully known; otherwise multiple logical records are valid. Updating `current_version_id/version` requires an optimistic review transaction.

### `approved_extraction_versions`

Immutable: `id`, `org_id`, `record_id`, `version`, `parent_version_id`, `origin_proposal_id`, `payload jsonb`, `comparability_key jsonb`, `evidence_manifest jsonb`, `evidence_manifest_hash`, `ontology_version`, `normalizer_version`, `validator_version`, `approved_by`, `approval_reason`, `created_at`. Unique `(record_id, version)`. No UPDATE/DELETE grants or policies.

### `confidence_calibrators`

Shared, tenant-neutral immutable trust artifact (no `org_id`): `id`, `output_family`, `version`, `dataset_id`, `dataset_hash`, `algorithm='isotonic-v1'`, `breakpoints jsonb`, `sample_count`, `metrics jsonb`, `artifact_hash`, `created_at`. The dataset must be an approved non-tenant release fixture; tenant-derived labels cannot enter this table. SELECT-only for application/worker roles and written only by the evaluation/release role.

## Payload unions

Common fields: `schema_version`, `entity_id`, `issuer_label`, `metric_id`, `raw_value`, normalized `value`, `unit`, `currency`, `scale`, `sign`, `period`, `dimensions`, `definition`, `qualifiers`, `reported_or_derived`, and evidence IDs.

- KPI requires decimal/count/ratio value plus ontology qualifiers.
- Guidance is discriminated by `shape`: point has `value`; range has `low/high`; floor has `low`; ceiling has `high`; qualitative has `text` and no numeric field.
- Revenue driver requires closed `category` (`price`, `volume`, `mix`, `acquisition`, `retention`, `usage`, `seats`, `fx`, `services`, `cost`, `other`), `description`, optional `direction` (`positive`, `negative`, `mixed`, `unknown`), target metric IDs, period, and evidence. It is a cited management assertion, not a validated causal estimate.

## Transactions and invariants

1. Run creation: authorize workspace, pin evidence/cutoff/policy, insert run + job + audit atomically.
2. Step checkpoint: lease-fenced worker transaction inserts successful step and events; proposal persistence is idempotent by deterministic proposal ID/hash.
3. Review: lock proposals/heads in UUID order, verify ETag versions and evidence, run validators, append review + audit + approved version, update states/heads, commit all-or-none.
4. Correction: append version `n+1`; update only head pointer. Prior version is immutable.
5. Merge: validate compatibility, create/advance surviving logical record, union sorted evidence manifest, supersede inputs, append one decision.
6. Service-role worker must query workspace ownership and include `org_id` in every write; API uses `fel_app` with `SET LOCAL` RLS.
7. Run completion: successful proposal persistence moves `running -> waiting_review`. When every proposal is terminal (`accepted`, `rejected`, or `superseded`) and no conflict is open, the review transaction moves `waiting_review -> succeeded`. A valid run with no proposals terminates `succeeded` with an explicit abstention outcome; provider/schema/budget failures terminate `failed` and never enter review.

## Required database tests

- RLS isolation for every table and each action.
- Immutable approved version and append-only review/event enforcement.
- Unique run/review idempotency under concurrency.
- Optimistic review conflict and deterministic lock ordering.
- Crash after each step, stale lease, and replay without duplicate provider calls/proposals.
- Cutoff, corpus-version, document-version, and span-hash failures.
- Concurrent corrections yield one version sequence with no lost update.
