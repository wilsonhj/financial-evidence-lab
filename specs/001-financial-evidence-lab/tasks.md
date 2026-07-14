# Financial Evidence Lab — Implementation Tasks

Tasks are ordered by dependency. A task is complete only when its code, tests, telemetry, documentation, and acceptance evidence are present.

## M0 — Platform and contracts

- [x] `T0001` Scaffold the monorepo, formatting, typing, unit tests, security scanning, and CI cache.
- [x] `T0002` Configure direct local Next.js/FastAPI/worker processes with mocked providers and hosted-Supabase environment placeholders; Docker is not required.
- [x] `T0003` Define OpenAPI and JSON-schema versioning rules and generate the TypeScript client.
- [x] `T0004` Implement Supabase Auth login, organizations, membership, and owner/editor/reviewer/viewer roles (`FR-WRK-001`–`004`).
- [x] `T0005` Enforce and test row-level tenant isolation, including negative cross-tenant tests.
- [x] `T0006` Create workspace APIs with entity, currency, fiscal calendar, scenario, and as-of cutoff.
- [x] `T0007` Establish immutable audit events, request IDs, traces, metrics, and structured logs.
- [x] `T0008` Implement usage metering, estimates, soft warnings, and hard-stop cost ceilings.
- [x] `T0009` Add Railway service configuration, Supabase SQL migrations, GitHub Actions gates, and backup-restore tests.
- [x] `T0010` Publish provider interfaces plus mock implementations for OpenAI, Supabase Storage, Alpha Vantage, SEC, and FRED; request credentials only when integration tests require them.

## M1 — Point-in-time evidence corpus

- [x] `T0101` Implement SEC entity and submission discovery with fair-access controls (`FR-ING-001`, `006`).
- [x] `T0102` Store immutable raw sources with hash, accession, URL, MIME type, and timestamps (`FR-ING-002`).
- [x] `T0103` Parse SEC HTML/iXBRL into document hierarchy, tables, facts, and stable source spans.
- [x] `T0104` Normalize XBRL decimals, units, scale, periods, dimensions, duplicates, and restatements.
- [x] `T0105` Implement idempotent, versioned jobs and atomic corpus publication (`FR-ING-003`–`005`).
- [x] `T0106` Quarantine malformed sources and expose actionable ingestion diagnostics (`FR-ING-007`).
- [x] `T0107` Implement vintage-aware FRED ingestion.
- [x] `T0108` Implement the Alpha Vantage BYO adapter with adjusted prices, volume, dividends, and splits (`FR-ING-008`).
- [x] `T0109` Reject forecast features with missing required adjustments or timestamps (`FOR-005`).
- [x] `T0110` Build the evidence reader with hierarchy, source highlights, fact metadata, duplicates, and amendments.
- [ ] `T0111` Create temporal-cutoff, parser golden-file, and idempotency test suites.
- [ ] `T0112` Ingest the first 20 benchmark issuers and record corpus-quality metrics.

## M2 — Observable hybrid retrieval

- [ ] `T0201` Implement finance-aware passage, table-row, and fact chunking with stable provenance.
- [ ] `T0202` Build PostgreSQL lexical and pgvector dense indexes (`FR-RAG-001`).
- [ ] `T0203` Implement structured fact/table lookup and entity/time/document filters (`FR-RAG-002`).
- [ ] `T0204` Implement the typed query plan and bounded query variants.
- [ ] `T0205` Add reciprocal-rank fusion and a pluggable reranker (`FR-RAG-003`).
- [ ] `T0206` Persist candidates, scores, filters, fusion, rejections, budgets, and latency (`FR-RAG-004`).
- [ ] `T0207` Implement atomic claims and closed claim/citation states (`FR-RAG-005`, `007`, `008`).
- [ ] `T0208` Implement citation entailment and numeric-consistency verification.
- [ ] `T0209` Implement abstention and qualified contradiction responses (`FR-RAG-006`).
- [ ] `T0210` Build the Search Observatory with lane toggles, trace timeline, evidence feedback, and replay.
- [ ] ~~`T0211` Generate and version passage/fact/company projections for the Embedding Atlas.~~ — deferred (post-MVP) with the Embedding Atlas.
- [ ] ~~`T0212` Build Atlas pan/zoom/filter/lasso/query-neighbor interactions (`UX-ATL-001`–`004`).~~ — deferred (post-MVP) with the Embedding Atlas.
- [ ] ~~`T0213` Add keyboard-accessible table and exact-distance fallback (`UX-ATL-005`).~~ — deferred (post-MVP) with the Embedding Atlas.
- [ ] `T0214a` Build the 50–100-question smoke benchmark and automate the Section 19.6 gates against it for the M2 exit (`spec.md` Section 19.5).
- [ ] `T0215` Run the reference-corpus retrieval performance suite (Atlas performance testing deferred post-MVP).

## M3 — Agentic extraction

- [ ] `T0301` Define the B2B SaaS ontology for ARR, retention, customers, seats, pricing, bookings, billings, and gross margin.
- [ ] `T0302` Implement bounded durable agent workflows with typed inputs/outputs and allowlisted tools.
- [ ] `T0303` Implement KPI, guidance, and revenue-driver extraction schemas and agents.
- [ ] `T0304` Implement period, currency, unit, sign, scale, and dimension normalization (`FR-EXT-001`, `002`).
- [ ] `T0305` Add deterministic accounting, schema, duplicate, and conflict validators.
- [ ] `T0306` Calibrate confidence and enforce the 0.85 record/0.80 field review thresholds (`EXT-005`).
- [ ] `T0307` Prevent auto-approval of monetary facts, guidance, and assumptions.
- [ ] `T0308` Build accept/edit/reject/merge/rerun review workflows (`FR-EXT-003`).
- [ ] `T0309` Version approved records and preserve correction history (`EXT-004`).
- [ ] `T0310` Pass extraction, numeric-accuracy, and contradiction release gates.

## M4 — Revenue and gross-profit model

- [ ] `T0401` Implement source, assumption, driver, formula, aggregation, scenario, forecast, validation, and output nodes.
- [ ] `T0402` Implement dependency edges, cycle detection, and versioned graph snapshots (`FR-MOD-001`).
- [ ] `T0403` Build the server-side decimal calculation engine with typed units (`FR-MOD-002`).
- [ ] `T0404` Connect approved extractions to source-backed model nodes (`FR-EXT-004`).
- [ ] `T0405` Implement sparse bull/base/bear scenario layers (`FR-MOD-003`).
- [ ] `T0406` Build the interactive driver graph and coordinated historical/forecast charts.
- [ ] `T0407` Add price-volume-mix bridges, revenue/gross-profit waterfalls, heatmaps, and tornado charts.
- [ ] `T0408` Implement formula, dependency, assumption, citation, diff, and restore views (`MOD-002`, `004`).
- [ ] `T0409` Add property tests for decimal arithmetic, units, periods, cycles, and scenario immutability.
- [ ] `T0410` Pass the 5,000-node p95 recalculation target.

## M5 — Forecast Lab and release

- [ ] `T0501` Define the common fit/predict/backtest interface and immutable forecast-run contract (`FR-FOR-001`, `002`).
- [ ] `T0502` Implement last-value and seasonal-naive quarterly baselines.
- [ ] `T0503` Implement analyst driver forecasts for revenue, ARR where disclosed, and gross profit.
- [ ] `T0504` Implement rolling-origin backtests for one-to-eight-quarter horizons.
- [ ] `T0505` Produce 50%, 80%, and 95% intervals and calibration metrics.
- [ ] ~~`T0506` Implement point-in-time historical analogue retrieval.~~ — deferred (post-MVP) with the analogue forecast lane.
- [ ] `T0507` Build Forecast Lab comparison, error, contribution, analogue, and uncertainty views.
- [ ] `T0508` Keep advanced models non-default unless they beat the seasonal-naive median-MAE gate.
- [ ] `T0509` Build complete source-to-export audit traversal.
- [ ] `T0510` Export Markdown/PDF briefs, CSV/XLSX tables, JSON evidence bundles, and workspace manifests.
- [ ] `T0511` Execute accessibility, security, load, restore, provider-failure, and browser suites.
- [ ] `T0214b` Complete the frozen, dual-adjudicated benchmark of at least 300 questions and automate the Section 19.6 gates against it (`spec.md` Section 19.5).
- [ ] `T0512` Verify every `spec.md` Section 19.6 gate and Section 26 definition-of-done item.
- [ ] `T0513` Produce the immutable MVP release artifact and signed evaluation report.
