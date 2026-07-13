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
