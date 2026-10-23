# Shared packages

Reusable libraries consumed by `apps/` and `workers/`. Path ownership for each
package is registered per work package in
[`docs/handoff/workstreams.yaml`](../docs/handoff/workstreams.yaml);
`packages/contracts/` is a shared path owned by the integration lead
(see [`AGENTS.md`](../AGENTS.md#shared-paths)).

| Package | Purpose | Language | Docs |
|---|---|---|---|
| `calculation-engine/` | Typed model graph and deterministic Decimal calculation engine for the Revenue Model Composer (M4) | Python (`fel-calculation-engine`) | [README](./calculation-engine/README.md), [#219 acceptance](./calculation-engine/ACCEPTANCE-219.md) |
| `contracts/` | Frozen OpenAPI and JSON Schema contracts, canonical fixtures, and the generated TypeScript client (ADR-0001) | OpenAPI / JSON Schema / TypeScript (`@fel/contracts`) | [README](./contracts/README.md), [versioning rules](./contracts/VERSIONING.md) |
| `ontology/` | B2B SaaS metric ontology (`saas-metrics/v1`) used by extraction | Python (`fel-ontology`) | [README](./ontology/README.md) |
| `providers/` | Provider protocols and deterministic mocks, plus explicit-key OpenAI adapters and an offline credential cipher | Python (`fel-providers`) | [OpenAI structured](./providers/OPENAI.md), [OpenAI embeddings](./providers/OPENAI_EMBEDDINGS.md), [credential cipher](./providers/CREDENTIAL_CIPHER.md) |
| `retrieval/` | Versioned hybrid retrieval backend: item building, index publish, cutoff-safe lanes, planning, RRF fusion, and persisted traces (M2) | Python (`fel-retrieval`) | [README](./retrieval/README.md), [acceptance](./retrieval/ACCEPTANCE.md) |
| `retrieval-evals/` | Retrieval smoke-benchmark tooling: checksum-pinned manifest compiler and release-gate metrics | Python | [README](./retrieval-evals/README.md) |
| `ui/` | Reserved for shared React UI; currently contains only `.gitkeep` | — | [README](./ui/README.md) |
