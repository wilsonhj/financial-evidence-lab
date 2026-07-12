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
