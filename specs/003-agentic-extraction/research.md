# M3 Agentic Extraction — Research and Decisions

**Date:** 2026-07-16  
**Scope:** T0301–T0310 implementation choices  
**Decision rule:** use the smallest architecture already approved by ADR-0002 unless measured requirements force more.

## 1. Repository baseline inspected

- Canonical product spec v1.2, plan, tasks, constitution, ADR-0002, contract versioning, and workstream ownership on current `main` (`70ee86f` when inspected).
- Platform migration `0001_platform_core.sql`: tenant tables, append-only audits, usage events, RLS, idempotency replay, and PostgreSQL jobs.
- Corpus migration `0002_corpus_core.sql`: immutable documents/versions, global source offsets/hashes, XBRL facts, corpus versions, and shared public corpus grants.
- Worker queue/consumer: `FOR UPDATE SKIP LOCKED`, short claim, 60-second stale threshold, 15-second heartbeat, lease fencing, retries, and idempotency.
- FastAPI auth/database patterns: non-privileged `fel_app`, `SET LOCAL request.jwt.claims`, membership re-resolution, ETag/If-Match, and contract error envelopes.
- Frozen contracts v0.2.0 and provider protocols. Current `LLMProvider.generate()` returns free text and exposes neither structured schema nor model usage metadata.
- Issues #60–#62. All still name `integration/m0`; #60 omits worker-dispatch/provider paths; no issue owns required contracts/migration.
- PR #75 and `integration/m0` ontology survey. Its 14-row normalized metric table and issuer-definition conflicts are useful inputs. A later integration-lead comment identified missing provenance artifacts, four under-cited issuers, and uncited/overstated survey claims; ontology v1 must not convert those uncorrected claims into guarantees.

## 2. External primary documentation

- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs — JSON Schema-constrained output, explicit refusals, and Pydantic/SDK integration support a typed provider boundary.
- PostgreSQL `SELECT`: https://www.postgresql.org/docs/current/sql-select.html — current locking behavior supports the existing `FOR UPDATE SKIP LOCKED` queue; no separate broker is needed.
- Pydantic discriminated unions: https://docs.pydantic.dev/latest/concepts/unions/ — tagged unions are appropriate for closed KPI/guidance/driver payload variants and predictable validation errors.

No Context7-specific evidence is required to choose a new framework because no new framework is proposed. Implementation agents should consult Context7/primary docs for the exact pinned OpenAI SDK, FastAPI, Pydantic, psycopg, and Next.js versions before coding.

## 3. Decisions

### D1 — Existing queue plus a persisted finite state machine

**Decision:** one `extraction_run` job executes a fixed stage graph and checkpoints each stage in PostgreSQL. Retry resumes from content-addressed completed stages. The existing lease fencing determines ownership.

**Why:** the repo already supplies durable claim/heartbeat/reaper semantics. M3 throughput and duration do not meet ADR-0002 triggers for a dedicated queue or WebSockets.

**Rejected:** Temporal, Celery/Redis, Kafka, LangGraph service, unconstrained agent loops. Each adds infrastructure without a measured requirement.

### D2 — Five roles, no agent-to-agent communication

**Decision:** implement the five parent-spec roles as typed stages: classifier, fact/table candidate extractor, KPI extractor, guidance extractor, and driver mapper. Only applicable extractors run. Deterministic stages assemble context, normalize, validate, verify citations, and detect conflicts.

**Why:** resolves the mismatch between the parent spec's five initial agents and #60's three named extractors while preserving the requirement that normalization/validation are not agents.

### D3 — Add a narrow structured-generation provider capability

**Decision:** add `StructuredLLMProvider.generate_structured(request) -> StructuredModelResult` as an additive provider contract. It accepts schema name/version and JSON Schema, returns parsed JSON, refusal state, provider/model ID, token usage, estimated cost, and response ID. Supply deterministic mock and OpenAI implementations.

**Why:** free-text `LLMProvider.generate()` cannot enforce typed output or capture the usage/version data required by the product spec. OpenAI Structured Outputs directly supports this boundary. The generic text provider remains for compatibility.

**Fallback:** an unsupported provider may use JSON text plus strict Pydantic validation and one repair attempt, but cannot be a production default until it passes the same contract/eval suite.

### D4 — Manual-only approval for M3

**Decision:** every proposal enters human review. Confidence thresholds set priority and block unsafe actions; they never auto-approve.

**Why:** simplest safe interpretation of the parent spec, removes an unnecessary policy branch, and strictly satisfies the prohibition on auto-approving monetary facts, guidance, and assumptions. A later ADR may introduce narrow auto-approval only with benchmark evidence.

### D5 — Immutable proposals, append-only decisions, immutable approved versions

**Decision:** proposals are versioned records; review decisions are append-only; accepted/corrected payloads are immutable approved versions; one RLS-protected head pointer identifies the current version.

**Why:** supports reconstruction, correction history, safe merge, and M4 consumption without mutating evidence.

### D6 — Evidence snapshot pinned at run creation

**Decision:** a run pins workspace, entity, cutoff, corpus version, selected source spans/claims, ontology/workflow/prompts/provider/model, and budgets. Evidence joins are revalidated in the worker despite service-role access.

**Why:** prevents look-ahead and confused-deputy tenant leaks, and makes reruns explainable.

### D7 — Preserve issuer definitions; comparability is explicit

**Decision:** ontology aliases assist classification but do not collapse definitions. Each metric has required qualifiers and a comparability key. Examples:

| Family | Required qualifiers for comparison |
|---|---|
| ARR/MRR | construction basis, scope, measurement date |
| NRR/GRR | base quantity, population, lookback, aggregation |
| Customer threshold | threshold amount/currency, comparator, ARR/ACV/TTM-revenue basis |
| Billings | issuer formula and deferred-revenue convention |
| RPO/cRPO | horizon, exemptions, dimensional verification |
| Gross margin | subscription/product/services basis, GAAP/non-GAAP |

**Why:** PR #75 demonstrates issuer-to-issuer definition conflicts that would make naive canonicalization misleading.

### D8 — Deterministic normalization with Decimal

**Decision:** retain raw text; convert numeric values to signed decimal strings; store scale, unit, currency, fiscal period, dimensions, formula, and lineage separately. Identify but do not convert currency.

**Why:** constitution and existing financial-fact contract forbid authoritative float math. Currency conversion is unnecessary for M3.

### D9 — Deterministic isotonic calibration

**Decision:** use a small pure-Python pool-adjacent-violators implementation per output family, persisted as JSON breakpoints with checksums. Fail closed when the labeled sample is insufficient.

**Why:** monotonic, explainable, deterministic, and does not add a runtime ML framework. Raw model confidence is not evidence confidence.

### D10 — PostgreSQL events for resumable SSE

**Decision:** append extraction events with identity IDs and expose them via SSE with `Last-Event-ID`; poll PostgreSQL and send 15–30 second heartbeats.

**Why:** matches the existing REST/SSE architecture and Railway limits. Runs checkpoint under 10 minutes.

## 4. Ontology v1 source synthesis

The reconciled PR #75 metric table supplies these initial IDs:

| ID | Canonical type | Value/period default | Important definition risk |
|---|---|---|---|
| `arr` | recurring revenue snapshot | USD/year, instant | MRR×12 versus contract value; scoped ARR |
| `mrr` | recurring revenue snapshot | USD/month, instant | issuer construction |
| `nrr` | retention ratio | percent, trailing window | ARR/ACV/revenue base; cohort/averaging |
| `grr` | retention ratio | percent, trailing window | churn/contraction inclusions |
| `cust_total` | customer count | count, instant | customer definition |
| `cust_threshold` | threshold cohort | count, instant | threshold and ARR/ACV/TTM basis |
| `seats` | user/seat count | count, instant | paid/licensed/active scope |
| `bookings` | contract-flow metric | USD, duration | often undefined; no assumed formula |
| `billings` | derived flow | USD, duration | revenue + delta-deferred convention |
| `rpo` | obligation balance | USD, instant | exemptions and usage contracts |
| `crpo` | current obligation balance | USD, instant | <=12-month slice needs verification |
| `deferred_rev` | liability balance | USD, instant | ASC 606 versus legacy tag families |
| `sub_gm` | derived margin | percent, duration | subscription versus product scope |
| `svc_gm` | derived margin | percent, duration | frequently negative; never proxy blended margin |

Guidance is a discriminated union (`point`, `range`, `floor`, `ceiling`, `qualitative`) over a metric/period. Revenue drivers use a closed first-pass category set (`price`, `volume`, `mix`, `acquisition`, `retention`, `usage`, `seats`, `fx`, `services`, `cost`, `other`) plus cited issuer wording and optional relationship direction; they are proposals, never authoritative causal claims.

## 5. Failure policy

| Failure | Deterministic behavior |
|---|---|
| Invalid request/source/cutoff | Reject before enqueue, typed 4xx |
| Provider timeout/transient error | One bounded retry if budget permits; otherwise failed run |
| Refusal | Record refusal; no repair; run may continue other independent extractors |
| Schema-invalid output | One repair call with validation errors only; then failed step/no proposals |
| Missing evidence | Abstain and emit no proposal for that candidate |
| Span hash/version mismatch | Integrity failure; proposal cannot be accepted |
| Validation failure | Persist proposal as needs-review with blockers |
| Conflicting sources/definitions | Preserve alternatives and conflict group |
| Budget/cancel/lease loss | Stop at next boundary; fenced worker cannot write terminal results |
| Review precondition race | 412, no partial changes |
| Merge incompatibility | 409 with field-level reasons |

## 6. Research risks carried into implementation

1. PR #75 is not fully provenance-complete despite being merged. Reconciliation must include or explicitly track the later review corrections; the ontology build must rely on cited definitions and machine-contract tests, not the survey's broad coverage claims.
2. M2 contracts are a hard dependency. If M2 does not expose a pinned evidence bundle with citations/conflicts, M3 must open a contract change rather than query around the cutoff.
3. Live OpenAI integration requires `FEL_OPENAI_API_KEY`; all CI and most acceptance tests remain mock-only. Request the credential only for the production adapter smoke test.
4. Database and public contracts are shared paths; they must merge before #60–#62 implementation branches.
