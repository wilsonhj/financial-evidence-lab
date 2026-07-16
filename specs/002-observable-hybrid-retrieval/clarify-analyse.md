# `/speckit.clarify` and `/speckit.analyse` — M2

## Clarifications resolved with approved defaults

| Question | Resolution |
|---|---|
| What is replay? | Re-emit stored immutable events. Rerun is a separate child run. |
| Which cutoff wins? | Effective cutoff is `min(workspace.as_of, requested as_of)`; request cannot widen scope. Inclusive `published_at <= cutoff`. |
| Which corpus/index? | Explicit ready/superseded pins or the atomic active defaults captured at query creation; never mixed during a run. |
| Stable IDs/reindexing? | UUIDv5 over index/kind/source anchor/content hash; config/model/chunker changes create a new index version. |
| Planner/provider? | Deterministic versioned synonyms, max four variants; no default LLM planning. |
| Fusion defaults? | Lane 100, RRF k=60, fused 100, context 16. Scores retained as decimal strings. |
| Reranker? | No-op interface unless checksum-frozen smoke Recall@10 <90%; then cross-encoder top 100. |
| Table provenance? | Exact canonical span required; unanchored rows rejected. |
| M2 benchmark? | Promote PR #74’s 65 rows through a compiler; smoke set need not be dual-adjudicated, but quotes/negative scope must validate. |
| Which gates apply? | M2 retrieval/citation gates only: temporal, numeric, entailment, completeness, Recall@10; guidance F1 begins M3. |
| Tenant boundary? | Index artifacts shared; queries/traces/feedback/claims/citations RLS-scoped. |
| Credentials? | Mock tests and fixture index first; request OpenAI credentials only for live benchmark/integration. |

## Analysis findings and resolutions

### High — Existing issues forbid required migration/contracts

Resolved: create one `contract-change` issue and ADR-0006; merge additive migration/OpenAPI first. Refresh #57–#59 dependencies/base/paths.

### High — PR #74 is absent from main and not executable

Resolved: reconcile two artifacts, preserve raw seed, compile a pinned manifest with unique evidence IDs and checksum. Negative cases specify searched corpus; ranges become low/high in compiled schema.

### High — Synthetic/live or cross-version evidence could mix

Resolved: every query pins corpus/index; candidate FK/version integrity is checked; no current-table scan without pin; report includes config hashes.

### High — Replay semantics were ambiguous

Resolved: stored replay versus unchanged child rerun versus a control-modified child query are distinct operations. SSE is keyed by run ID and query snapshots enumerate run history for comparison.

### High — Trace contract could not render the promised Observatory

Resolved: aggregate candidates retain every lane/variant contribution; the trace now includes lineage/config hashes, ordered decisions, timing, budget usage, cost, parent run, and run history.

### High — Public corpus ADR does not cover tenant traces

Resolved: explicit RLS on all analysis records and cross-tenant negative tests; only derived index artifacts inherit ADR-0004.

### Medium — Table rows lack guaranteed span anchors

Resolved: indexer must create/resolve exact canonical offsets and hash or reject `UNANCHORED_TABLE_ROW`; rejected rows never enter context.

### Medium — RRF/reranker/query budgets unspecified

Resolved with defaults above and persisted config.

### Medium — ANN recall and filtered queries under-specified

Resolved: exact oracle, HNSW cosine halfvec, iterative relaxed scan, per-run `ef_search`, recall/latency tuning report.

### Medium — SSE could lose events/reconnect incorrectly

Resolved: persist-before-send, ordered sequence, Last-Event-ID, heartbeat, terminal event, reconnect tests.

### Medium — Metric denominators/negative cases unclear

Resolved: report numerator/denominator and fail on zero eligible denominator; Recall@10 is macro mean over answerable questions using stable golden evidence; temporal validity checks every returned candidate; citation metrics operate on produced factual claims; abstention scored separately.

### Medium — Parallel ownership conflicts

Resolved: contract/migration wave first; backend and mock UI can then work in disjoint paths; claims package waits for backend schema. M2 API/web packages must not overlap concurrent M2/M3 owners.

### Medium — Deterministic item IDs depended on random index IDs

Resolved: index-version UUIDv5 and a unique pinned-input tuple reuse identical builds; item UUIDv5 values are therefore stable across identical rebuilds.

## Result

No unresolved high/medium findings. Low follow-ups: expand four uncovered issuers, diversify restatement cases, and calibrate `ef_search` on the final reference corpus.
