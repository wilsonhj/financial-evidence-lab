# M2 Implementation Tasks

## Phase 0 — Contract and migration gate

- [ ] **M2-001** Merge issue #100 against accepted ADR-0006: additive OpenAPI/JSON Schema v0.3.0, generated TS client, and drift tests.
- [ ] **M2-002** Add migration for index artifacts and tenant trace/claim tables, grants, RLS, append-only rules, and negative isolation tests.

## Package A — Retrieval backend (#57)

- [ ] **M2-010** Implement canonical passage/table-row/fact item builder with UUIDv5 IDs, global offsets, hash verification, rejection diagnostics, and idempotency tests (T0201).
- [ ] **M2-011** Implement versioned index build/publish; 512d mock/OpenAI embeddings; FTS GIN and halfvec cosine HNSW; exact oracle (T0202).
- [ ] **M2-012** Implement four cutoff-safe lanes with corpus/index pinning and fact/table mapping (T0203).
- [ ] **M2-013** Implement typed deterministic planner, synonym map, filter validation, max-four variants and budgets (T0204).
- [ ] **M2-014** Implement concurrent lanes, evidence dedupe, RRF k=60, no-op reranker interface and traceable top-100 hook (T0205).
- [ ] **M2-015** Persist ordered events/candidates/decisions/timings/budgets; implement create/read/SSE/rerun/feedback APIs and reconnect tests (T0206).

## Package B — Claims and evaluation (#58; after A)

- [ ] **M2-020** Implement structured answer generation and atomic closed claim states (T0207).
- [ ] **M2-021** Implement citation entailment interface plus deterministic Decimal numeric tuple validator and cross-version integrity checks (T0208).
- [ ] **M2-022** Implement evidence insufficiency/contradiction rules and abstention (T0209).
- [ ] **M2-023** Reconcile PR #74 artifacts; compile a checksum-pinned 65-question manifest; validate every evidence acceptance/publication timestamp against `as_of`; correct provisional midnight cutoffs; verify negative-case corpus scope; and normalize ranges (T0214a).
- [ ] **M2-024** Implement metrics, per-lane ablations, exact-vs-HNSW recall, release gate report and scaled/reference performance suite (T0214a/T0215).

## Package C — Observatory UI (#59; after A contract)

- [ ] **M2-030** Implement server-only authenticated query source and resumable SSE client.
- [ ] **M2-031** Render plan, lane columns, score/rank explanations, filter/rejection timeline, budgets, claims and citation links.
- [ ] **M2-032** Add bounded lane/top-k/time controls, rerun/compare, feedback and stored replay.
- [ ] **M2-033** Add keyboard table/text alternatives, WCAG 2.2 AA tests, error/abstention states and browser E2E (T0210).

## Integration/verification

- [ ] **M2-040** Run worker/index -> Postgres -> API/SSE -> web acceptance with a non-first-section citation, fact, table row, cutoff trap, contradiction and abstention.
- [ ] **M2-041** Meet all M2 gates, `make ci`, independent PR reviews, migration restore smoke, and publish immutable evaluation report.

Parallelism: after M2-001/002 merge, A owns `packages/retrieval/**`, `apps/api/**`, migration already frozen; C may build UI against mocks in `apps/web/**` and `packages/ui/**`. B starts after A retrieval contract is stable. Do not overlap API/shared paths.
