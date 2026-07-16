# M3 Agentic Extraction — Feature Specification

**Status:** Clarified and implementation-ready  
**Version:** 1.0.0  
**Date:** 2026-07-16  
**Parent specification:** `specs/001-financial-evidence-lab/spec.md` v1.2  
**Tasks:** T0301–T0310  
**Dependencies:** M2 claims verification merged; contract-change issue #101 (v0.4.0) merged; PR #75 ontology research reconciled to `main`

## 1. Outcome

M3 turns cutoff-safe evidence from M2 into typed, normalized, cited proposals for B2B SaaS KPIs, management guidance, and revenue drivers. A bounded PostgreSQL-backed workflow records every step. Deterministic code—not a language model—normalizes values, verifies citations, detects duplicates/conflicts, applies review policy, and versions approved records. Reviewers can accept, edit, reject, merge, or rerun without losing provenance.

The MVP deliberately uses one worker process, the existing PostgreSQL job queue, FastAPI, and the current Next.js app. It adds no orchestration service, message broker, cache, or autonomous agent-to-agent conversation.

## 2. Scope

### In scope

- Versioned B2B SaaS ontology for ARR, MRR, retention, customer cohorts, seats/users, bookings, billings, RPO/cRPO, deferred revenue, and subscription/services gross margin.
- Five bounded workflow roles required by the parent spec: document/section classifier, financial-fact/table candidate extractor, KPI extractor, guidance extractor, and revenue-driver mapper.
- Deterministic period, currency, unit, sign, scale, dimension, definition, duplicate, accounting, conflict, and citation validation.
- Immutable run/step/event records and resumable execution using the existing PostgreSQL queue.
- Versioned extraction proposals with record- and field-level calibrated confidence.
- Tenant-scoped review queue and accept/edit/reject/merge/rerun actions, including bulk review.
- Immutable approved-record versions and an auditable current-version pointer.
- SSE run events with resumable event IDs.
- Evaluation fixtures and release-gate reports for guidance and KPI/driver extraction.

### Out of scope

- Free-form multi-agent conversations or model-created tools.
- Redis, Celery, Kafka, Temporal, or a separate orchestration service.
- LLM-executed financial calculations.
- Automatic approval in M3. All proposals require explicit human approval; this conservative default satisfies the stricter monetary/guidance/assumption rule and can be revisited only with a later policy ADR and benchmark evidence.
- Dedicated contradiction-detection agent. Contradiction detection remains owned by M2 claim/citation verification (`FR-RAG-008`). M3 consumes its conflicting spans and adds extraction-level duplicate/definition conflict handling.
- Full financial-model graph creation (M4).
- Entity/product resolver and risk detector agents (post-MVP).

## 3. Users and permissions

| Action | owner | editor | reviewer | viewer |
|---|---:|---:|---:|---:|
| Create/cancel/rerun extraction run | yes | yes | no | no |
| Read runs, proposals, evidence, events | yes | yes | yes | yes |
| Accept/edit/reject/merge proposals | yes | yes | yes | no |
| Change extraction policy/thresholds | yes | no | no | no |

Membership is resolved from PostgreSQL; role claims alone are never trusted. All analysis records carry `org_id` and use RLS. Public source evidence remains shared and read-only.

## 4. User stories and independent acceptance

### US1 — Run a traceable extraction (P1)

An editor selects cutoff-visible evidence in a workspace and requests KPI, guidance, driver, or all extraction modes. The API creates one idempotent run, enqueues it, and immediately returns the run ID. The UI streams a finite execution graph showing inputs, step state, model/schema/workflow versions, cost, and failures.

Acceptance:

1. Replaying the same `Idempotency-Key` returns the same run and creates no second job.
2. Every source span belongs to a parsed document version in the pinned corpus and has `published_at <= run.as_of`.
3. A crash after any completed step resumes from the next incomplete step without duplicating proposals or model calls already committed.
4. No workflow exceeds its stored hard limits.

### US2 — Review cited normalized proposals (P1)

A reviewer sees each proposal beside exact source evidence, issuer definition, raw value, normalized value, period, dimensions, confidence, validations, and conflicts. The reviewer can accept, edit, or reject individually or in bulk.

Acceptance:

1. Monetary numeric proposals cannot be accepted without entity, period, unit, scale, sign, currency, and verified source span.
2. Guidance keeps `point`, `range`, `floor`, `ceiling`, or `qualitative`; range bounds cannot be reversed.
3. A validation failure or unresolved conflict prevents acceptance until edited or explicitly resolved.
4. Bulk review is atomic: all selected items succeed or none change.
5. Viewer review attempts return 403; stale ETags return 412.

### US3 — Preserve corrections and merges (P1)

A reviewer corrects an approved record or merges duplicate proposals. The prior approved version stays immutable; a new version records the parent, actor, reason, payload, evidence manifest, and timestamp.

Acceptance:

1. Approved version rows cannot be updated or deleted by application roles.
2. A correction creates version `n+1` and advances the head pointer transactionally.
3. Merge requires two or more compatible records, preserves every source edge, names the surviving logical record, and supersedes—never deletes—the inputs.
4. Full history can reconstruct every visible state.

### US4 — Handle conflicting definitions safely (P2)

The system preserves issuer-specific metric definitions and marks non-comparable values rather than collapsing aliases such as ARR/ACV, NRR/net expansion, or RPO/cRPO.

Acceptance:

1. Alias match never implies comparability.
2. Comparable records must match the ontology `comparability_key` fields.
3. Differing value, period, definition, scope, or source for the same canonical key creates a conflict group.
4. Conflicting alternatives remain visible until a reviewer resolves them.

### US5 — Calibrate and evaluate (P2)

A trust engineer generates a versioned confidence artifact and extraction evaluation report from adjudicated fixtures.

Acceptance:

1. Calibrated confidence is produced by deterministic versioned code; raw model self-confidence is retained only as an input feature and never used directly as approval confidence.
2. Missing/insufficient calibration data fails closed to confidence `0` and review priority `high`.
3. Guidance extraction F1 is at least 90%; KPI/revenue-driver F1 is at least 88%; numeric value/unit/period/sign/scale accuracy is at least 99%.
4. The report records dataset, ontology, workflow, prompt, model, and calibrator versions and hashes.

## 5. Functional requirements

### Ontology and schemas

- **M3-ONT-001:** Publish `saas-metrics.v1.json` under `packages/ontology/` and validate it in CI.
- **M3-ONT-002:** The initial ontology contains the 14 normalized metrics from the reconciled PR #75 survey: `arr`, `mrr`, `nrr`, `grr`, `cust_total`, `cust_threshold`, `seats`, `bookings`, `billings`, `rpo`, `crpo`, `deferred_rev`, `sub_gm`, and `svc_gm`.
- **M3-ONT-003:** Every metric declares aliases, value type, canonical unit, period semantics, required qualifiers, derivation policy, comparability key, and review policy.
- **M3-ONT-004:** Issuer-reported definitions and scope qualifiers are preserved verbatim by source span; ontology aliases never erase them.
- **M3-SCH-001:** Provider outputs, persisted proposals, review commands, events, and approved records validate against the versioned schemas in `contracts/schemas/`, including the closed KPI/guidance/revenue-driver payload union; fixtures for every variant validate in CI.
- **M3-SCH-002:** Numeric values are signed decimal strings. Monetary values use base-currency units plus integer source scale; binary floating point is forbidden.

### Workflow

- **M3-WF-001:** A run pins `workspace_id`, `entity_id`, `as_of`, `corpus_version_id`, input source IDs, ontology version, workflow version, prompt versions, provider, and model.
- **M3-WF-002:** The finite step order is: validate request; assemble evidence; classify; collect fact/table candidates; run applicable KPI/guidance/driver extractors; normalize; validate; verify citations; detect duplicate/conflict; persist proposals; wait for review.
- **M3-WF-003:** Steps never message one another. Each receives a committed typed input and returns a typed output.
- **M3-WF-004:** Each model step permits at most two attempts: one initial call and one schema-repair call. No recursive repair is allowed.
- **M3-WF-005:** Default hard limits are 10 model calls, 100,000 input tokens, 20,000 output tokens, USD 2.00 estimated cost, and 600 seconds wall time per run. A request may set lower values; only an owner policy update may raise organization ceilings.
- **M3-WF-006:** At each boundary the worker checks cancellation, lease ownership, elapsed time, calls, tokens, and cost. Exceeding a hard limit terminates the run with a typed reason and emits no unvalidated proposal.
- **M3-WF-007:** Completed steps are content-addressed by `(run_id, step_name, input_hash, workflow_version)` and reused on retry. A changed input/version creates a new attempt.
- **M3-WF-008:** Retrieved filing content is untrusted data, cannot modify instructions or tools, and is delimited separately from system instructions. Tools are fixed per role and all arguments are validated.
- **M3-WF-009:** Tool allowlist is read-only: pinned evidence bundle lookup, ontology lookup, XBRL fact lookup within the pinned document version, and deterministic normalization/validation. No general network, shell, SQL, or arbitrary URL tool is exposed to a model.
- **M3-WF-010:** Successful proposal persistence moves the run to `waiting_review`; the last all-terminal proposal disposition with no open conflict moves it to `succeeded`. A valid zero-proposal abstention succeeds explicitly; provider/schema/budget failures fail before review.

### Normalization and validation

- **M3-NRM-001:** Normalize raw numeric text into `value`, `sign`, `scale`, `unit`, `currency`, `period`, and `dimensions` without changing the captured raw value.
- **M3-NRM-002:** Fiscal period resolution uses the workspace fiscal calendar and evidence date; ambiguity blocks approval.
- **M3-NRM-003:** Currency conversion is out of scope. Currency is identified, not converted; missing currency on a monetary value blocks approval.
- **M3-NRM-004:** Derivations use `Decimal`, a named formula version, supported input IDs, and calculation lineage.
- **M3-VAL-001:** Validators cover schema, decimal/unit/period/sign/scale, ontology qualifiers, source hash/offset, arithmetic identities, range ordering, duplicate keys, conflicting values/definitions, and cross-version evidence.
- **M3-VAL-002:** Citation verification re-hashes the exact canonical global text slice. A mismatch blocks approval and is visible as an integrity error.
- **M3-VAL-003:** XBRL-backed RPO/deferred-revenue values prefer ASC 606 concepts and retain legacy tag evidence; cRPO is extraction-assisted unless its timing dimension is verified.
- **M3-VAL-004:** Calculated billings records the issuer formula convention and may be derived only from cited revenue and deferred-revenue inputs from compatible periods.

### Proposals, review, and versions

- **M3-REV-001:** Proposal states are the closed set `proposed`, `needs_review`, `accepted`, `rejected`, `superseded`.
- **M3-REV-002:** Every M3 proposal enters `needs_review`; M3 has no automatic approval.
- **M3-REV-003:** Review actions are the closed set `accept`, `edit`, `reject`, `merge`, `rerun`. `rerun` creates a new run linked to the prior run; it does not mutate proposals.
- **M3-REV-004:** Review commands require `Idempotency-Key`, actor authorization, and an `expected_versions` entry for every selected proposal; an atomic batch fails with 412 if any version differs. Approved-record corrections additionally require `If-Match`. Edit, reject, merge, conflict override, and correction require a non-empty reason.
- **M3-REV-005:** Accept/edit re-runs all deterministic validators in the same transaction before writing an approved version.
- **M3-REV-006:** Merge is permitted only for identical entity, metric, period, dimensions, definition/comparability key, and unit/currency. Otherwise it returns 409.
- **M3-REV-007:** Accepted outputs are immutable versions. The correction endpoint accepts a fully schema-valid replacement payload/evidence set, re-runs validators, creates a child version, and atomically updates one head pointer.
- **M3-REV-008:** Every policy/run/step/proposal/review/version transition writes an append-only audit event.
- **M3-REV-009:** Owners, editors, and reviewers may explicitly approve monetary facts, guidance, and assumptions; they can never be approved by workflow policy or bulk automation without a human actor.

### API and events

- **M3-API-001:** Implement the endpoints in `contracts/extraction-api.yaml` and regenerate the TypeScript client in the contract-change PR.
- **M3-API-002:** Non-2xx responses use the existing error envelope. RLS-hidden resources return indistinguishable 404s.
- **M3-API-003:** Run events validate against `extraction-event/v1`, use monotonically increasing IDs, 15–30 second heartbeats, and `Last-Event-ID` replay.
- **M3-API-004:** List endpoints use stable cursor pagination and deterministic ordering.
- **M3-API-005:** The review UI shows execution graph, proposal/evidence side-by-side view, validations/conflicts, confidence, and version history without rendering unsanitized filing HTML.

### Confidence and gates

- **M3-CAL-001:** Use deterministic isotonic calibration (`isotonic-v1`) per output family on a versioned adjudicated dataset; persist breakpoints, sample counts, metrics, and SHA-256.
- **M3-CAL-002:** Record confidence is the minimum calibrated required-field confidence, reduced to zero by a citation-integrity failure; field confidence is calibrated independently where labels exist.
- **M3-CAL-003:** Policy defaults remain record `0.85` and field `0.80`. Changes are owner-only, bounded to `[0,1]`, versioned, and audited.
- **M3-CAL-004:** Any record below `0.85`, field below `0.80`, failed validation, or conflict receives `high` review priority. All other M3 records still require review.
- **M3-EVAL-001:** Evaluation uses exact ontology/period/unit/sign/scale matches; partial string similarity cannot count as correct numeric extraction.
- **M3-EVAL-002:** M3 passes parent-spec Section 19.6 guidance and KPI/driver F1 gates and the 99% numeric gate on its adjudicated extraction subset. M2 contradiction results are referenced, not reimplemented.

## 6. Non-functional requirements

- **Temporal:** 100% cutoff validity. Direct IDs, source joins, reruns, and approved records cannot reveal post-cutoff evidence.
- **Isolation:** Negative cross-tenant tests for every table and endpoint; workers validate `org_id`/workspace ownership before service-role writes.
- **Durability:** No committed proposal without committed run/step/evidence records; retry is idempotent.
- **Performance:** POST run p95 < 500 ms excluding auth/DB connection; review mutation p95 < 1 s on 100-item bulk action; event reconnect returns missed events within 2 s in reference test environment.
- **Availability:** Provider timeout/failure produces a typed terminal or reviewable failure; never a fabricated empty success.
- **Security:** No source text or secrets in logs; prompts and raw provider outputs are stored only in approved encrypted/object storage or hashed/redacted fields according to retention policy.
- **Observability:** Structured logs and metrics include run/step IDs, durations, attempts, tokens, estimated cost, validation counts, review outcomes, and error codes without evidence text.
- **Accessibility:** Review graph has an equivalent keyboard-accessible step table; status, conflict, and confidence do not rely on color alone.

## 7. Success criteria

M3 is complete only when:

1. T0301–T0310 implementation, tests, telemetry, docs, and acceptance evidence are present.
2. Every workflow/review/database/API contract test passes under mock providers.
3. A credentialed OpenAI smoke run produces schema-valid proposals while the same fixtures pass deterministically with the mock provider.
4. Temporal, RLS, crash-resume, idempotency, budget, prompt-injection, corrupt-span, conflict, and immutable-history tests pass.
5. Guidance F1 >= 90%, KPI/revenue-driver F1 >= 88%, and numeric accuracy >= 99% on the versioned adjudicated extraction set.
6. No proposal auto-approves, and every approved record has stable source evidence and complete audit history.
7. `make ci` and generated-contract drift checks pass.

## 8. Assumptions and resolved defaults

- `main` is the only implementation base; stale `integration/m0` wording is removed from issues.
- PR #75 is research input, not a runtime contract. Outstanding provenance/coverage corrections from its post-merge review must be resolved or explicitly carried as limitations before freezing ontology v1.
- M2 supplies cutoff-safe source spans, claims, citations, and contradiction states.
- One extraction job may checkpoint multiple model steps; the existing queue lease/heartbeat/reaper remains authoritative.
- M3 manual-only approval is the simplest safe policy. Thresholds rank and block review; they do not auto-approve.
- No currency conversion occurs in extraction.
- The first live provider is OpenAI structured output behind an additive provider interface; CI remains credential-free through deterministic mocks.
