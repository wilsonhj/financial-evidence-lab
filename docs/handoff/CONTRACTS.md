# Contract freeze protocol

Broad parallel work starts only after `M0-SCAFFOLD` and `M0-CONTRACTS` merge.

The initial freeze covers:

- monorepo directory and package boundaries;
- OpenAPI and JSON Schema versioning;
- generated TypeScript client conventions;
- authentication claims, organization roles, and tenant context;
- workspace identifiers and as-of cutoff semantics;
- job envelope, idempotency key, retry, and terminal states;
- provider interfaces and mock behavior;
- evidence identifiers, temporal fields, and source-span shape; and
- fixture/schema version identifiers.

A contract change requires:

1. an ADR under `docs/decisions/`;
2. a GitHub issue labeled `contract-change`;
3. affected-package and migration analysis;
4. updated contract tests and generated artifacts; and
5. integration-lead approval before dependent packages rebase.

Agents must not infer compatibility from similar field names. Versions and deterministic contract tests decide compatibility.

## Frozen artifacts (contract version 0.1.0)

Effective on the `M0-CONTRACTS` merge, the freeze is embodied in
`packages/contracts/`:

| Artifact | Contents |
|---|---|
| `openapi/openapi.yaml` (v0.1.0) | `/health`, workspaces (create/list/get/patch with ETag + If-Match), entities, documents with `as_of` filtering, source spans, ingestion jobs (Idempotency-Key, 202 + run-ID); error envelope on every non-2xx |
| `schemas/*.schema.json` (all v1) | source-span, financial-fact (decimal-string values), claim (closed status set), citation (closed entailment set), job-envelope (terminal states succeeded/failed/cancelled; queue/priority/heartbeat), tenant-context (owner/editor/reviewer/viewer), error |
| `fixtures/*.json` | Canonical valid examples, CI-validated |
| `src/generated/api.ts` | TypeScript client types; `check:generated` fails CI on drift |
| `VERSIONING.md` | The frozen semver rules and change process |

Provider interface and mock-behavior contracts are delivered by
`M0-PLATFORM` (T0010) as an additive minor version under these rules.

One exception is recorded: the exact provider interfaces (final freeze-list
bullet) ship with T0010 because their shapes depend on the mock
implementations built alongside them; they enter the freeze at that merge.

- **v0.2.0** (2026-07-15, PR #92, ADR-0005): additive reader composite endpoint `GET /v1/documents/{documentId}/reader`; `FinancialFact` promoted into generated types via file `$ref`; `reader-response/v1` schema + fixture + drift gate.
- **v0.3.0** (2026-07-16, issue #100, ADR-0006): additive observable retrieval surface — `POST /v1/workspaces/{workspaceId}/queries` (optional create pins resolved at query creation), query snapshot + rerun, typed resumable SSE (`run_cancelled` included), trace read, append-only evidence feedback with supersession; required resolved `QueryPlan.corpus_version_id` / `index_version_id`; schemas/fixtures for `query-plan`, `retrieval-event`, `retrieval-trace`, `evidence-feedback`; migration `db/migrations/0003_retrieval_core.sql` (shared immutable index artifacts, temporal/provenance guards, tenant query/trace/claim RLS). Leaves `0004_extraction_core.sql` for #101.
- **v0.4.0** (2026-07-19, issue #101, ADR-0007): additive bounded extraction surface — extraction runs (required `modes`), typed resumable SSE (`ExtractionEvent`), proposals/review, approved versions/corrections; schemas/fixtures for `extraction-payload`, `extraction-event`; migration `db/migrations/0004_extraction_core.sql` (policies/runs/steps/events/proposals/evidence/conflicts/reviews/approved versions + shared `confidence_calibrators`, RLS/immutability/idempotency); additive `StructuredLLMProvider` + deterministic mock in `packages/providers` (no live OpenAI adapter). Compatible open-enum loosening on volatile M2 labels: `QueryPlan.intent` / `lanes.items`, `candidateContribution.lane`, `decision.stage`, `RetrievalEvent.type` (`x-fel-open-enum: true`); extraction/retrieval mode and evidence-feedback labels remain closed.
- **v0.5.0** (2026-09-02, issues #194 / #193 / #157, ADR-0011 + ADR-0012): additive minor. (a) `claims-output/v1` schema + fixture registered in `SCHEMA_IDS` — the reader's structured-generation contract, consumed by `StructuredClaimGenerator` and produced by the deterministic mock model; optional members are modelled required-and-nullable so the same object can be sent to a strict structured-output provider unchanged. This is the entry previously carried as **Pending**; it landed with no HTTP surface of its own and takes its version pin from this release, as that entry said it would. (b) `ExtractionProposal.record_confidence` widens to `type: ["string", "null"]` and stays in `required` (issue #194) — NULL means "not yet scored" and is not comparable with `"0"`; the extraction worker persists NULL until #62 ships the calibrator, and `db/migrations/0006_extraction_step_output.sql` drops the column's `NOT NULL` to match. `field_confidences` stays non-nullable (`NOT NULL DEFAULT '{}'` in `0004`). (c) The `x-fel-status: planned` marker convention is documented above `paths`, and `apps/api/tests/test_openapi_parity.py` asserts the implemented route table equals exactly the unmarked path items in both directions. (d) `limit` query parameter (`components/parameters/ListLimit`) on the list endpoints. (e) 413 `READER_TOO_LARGE` on the reader endpoint. (f) `extraction_run_steps` gains `output`/`output_hash` per ADR-0011 (migration `0006`), which is what makes the published metadata-only event-payload guarantee literally true.

  **ADR-0011's open contract-version question is hereby answered: minor (0.5.0), not major.** ADR-0011 left Reading A (additive) and Reading B (breaking) unresolved for the implementing PR. Reading A is correct, on the reasoning the extraction agent recorded: `ExtractionEvent.payload` keeps `type: object` with `additionalProperties: true` and its description is untouched, so nothing declared is removed, renamed, retyped or newly required; every `$id` is unchanged (`extraction-event/v1` included); and `stage_output` was **never a declared property** — it rode inside a free-form `additionalProperties: true` bag, so dropping it removes nothing the contract ever promised, and there is no consumer today because no service implements the stream. Reading B treats an undeclared key inside an open object as part of the contract surface; under `VERSIONING.md` it is not. Precedent agrees on the digit either way (0.1.0 → 0.2.0 → 0.3.0 → 0.4.0), so the reading only ever decided whether 1.0.0 was warranted; it is not. `VERSIONING.md` now states the corresponding rule explicitly: a nullable widening that keeps the property `required` is additive.
