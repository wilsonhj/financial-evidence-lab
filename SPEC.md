# Financial Evidence Lab — Product and Technical Specification

**Status:** Clarified and implementation-ready
**Version:** 1.1
**Date:** 2026-07-11
**Owner:** wilsonhj
**Working name:** Financial Evidence Lab (FEL)

---

## 1. Executive summary

Financial Evidence Lab is a visual research and modeling environment for public-company analysis. It combines:

- semantic and lexical search over filings and related evidence;
- structured retrieval of XBRL financial facts and tables;
- agent-assisted extraction of KPIs, guidance, risks, and revenue drivers;
- point-in-time forecasting and scenario analysis;
- interactive revenue and gross-profit models; and
- claim-level provenance from source document through calculation to output.

The primary product differentiator is **visible reasoning infrastructure**. Retrieval, extraction, transformations, assumptions, and forecasts are inspectable. The application must not present an opaque chat answer as the terminal experience.

The initial release is a team-oriented SaaS product for public-equity analysts researching US-listed B2B SaaS companies. It uses SEC data, FRED macro series, and a bring-your-own market-price adapter. The MVP models revenue and gross profit; complete three-statement modeling and valuation are deferred. It is a research and decision-support product, not an autonomous trading system or source of personalized investment advice.

---

## 2. Problem

Investment research is fragmented across filing viewers, search tools, spreadsheets, charting systems, note-taking applications, and general-purpose AI assistants. This creates recurring problems:

1. Evidence is separated from the claims and model assumptions derived from it.
2. Filing text, tables, XBRL facts, market data, and time series are retrieved using different tools.
3. Generic vector search misses exact terminology, numeric facts, document hierarchy, and temporal constraints.
4. Analysts repeatedly transcribe KPIs and guidance into spreadsheets.
5. Forecasts often hide assumptions, uncertainty, and information cutoff dates.
6. Conventional chat interfaces obscure why evidence was retrieved or rejected.
7. Reproducing an analysis after new information arrives is difficult.

### Product opportunity

Build a workspace in which the analyst can move from corpus exploration to cited answers, validated extraction, driver modeling, forecasting, and exported research without breaking provenance.

---

## 3. Product principles

1. **Evidence before eloquence.** Unsupported output is visibly incomplete.
2. **Time is part of every fact.** The system distinguishes publication time, filing time, fiscal period, and model cutoff.
3. **Math is deterministic.** Language models may propose formulas but do not execute authoritative financial calculations.
4. **Humans approve consequential transformations.** Low-confidence extraction and changes to model assumptions require review.
5. **Retrieval is observable.** Users can inspect query plans, candidates, scores, filters, reranking, and citations.
6. **Uncertainty is rendered.** Forecasts show ranges, scenarios, and historical error—not only point estimates.
7. **Visualizations answer questions.** Decorative charts and misleading embedding projections are avoided.
8. **Provider portability.** LLM, embedding, reranking, storage, and market-data providers sit behind interfaces.

---

## 4. Goals and non-goals

### 4.1 Goals

- Make research over filings and financial facts faster and more auditable.
- Expose vector embeddings, hybrid retrieval, agent workflows, and model lineage visually.
- Turn cited qualitative evidence into reviewable financial drivers.
- Support repeatable point-in-time scenarios and revenue forecasts.
- Provide evaluation hooks for retrieval quality, extraction accuracy, forecast error, and citation fidelity.
- Support single-company analysis first and cross-company comparison second.
- Support collaborative team workspaces with attributable review and approval.

### 4.2 Non-goals for the MVP

- Autonomous trade execution or brokerage integration.
- Personalized investment recommendations.
- High-frequency or intraday forecasting.
- Full accounting close, ERP, or portfolio-accounting functionality.
- Automated ingestion of licensed research without explicit data rights.
- A complete Excel replacement.
- Full three-statement modeling, discounted-cash-flow valuation, and price-target generation.
- General PDF or user-upload ingestion; the MVP supports SEC HTML/iXBRL and configured structured data only.
- Training a foundation model.
- Multi-jurisdiction filing support beyond architecture-level extensibility.

---

## 5. Target users and jobs

### 5.1 Primary personas

| Persona | Core job | Primary value |
|---|---|---|
| Public-equity analyst | Research a company and maintain a thesis | Faster evidence synthesis and model updates |
| Investor or portfolio manager | Challenge assumptions and compare scenarios | Clear provenance and sensitivity analysis |
| Corporate finance/strategy analyst | Model business drivers and competitors | Visual revenue model and peer evidence |
| Financial-data engineer | Build reliable ingestion and retrieval | Typed, temporal, testable data contracts |

The launch persona is the **public-equity analyst working in a team**. Portfolio managers are reviewers and consumers of the same artifacts. The initial design-partner and evaluation cohort covers US-listed B2B SaaS companies.

### 5.2 Key jobs to be done

- “Show me what changed in management’s demand commentary over eight quarters.”
- “Find the source and context for reported segment revenue.”
- “Extract management guidance and reconcile it with actual results.”
- “Identify the drivers behind gross-margin expansion.”
- “Convert disclosed operating metrics into a revenue model.”
- “Compare the current setup with historically similar periods without look-ahead bias.”
- “Explain exactly which evidence and assumptions produced this forecast.”

### 5.3 Resolved product constraints

| Decision | MVP choice | Consequence |
|---|---|---|
| Deployment | Team-oriented SaaS | OIDC, organizations, collaboration, tenant isolation, and managed infrastructure are required |
| Financial model | Revenue and gross profit | Full statements and valuation remain post-MVP |
| Initial vertical | B2B SaaS | Initial ontology covers ARR, retention, customers, seats, pricing, bookings, billings, and gross margin |
| Embedding Atlas | Required MVP capability | Atlas delivery and acceptance tests are P0 |
| Market data | Bring-your-own provider | A provider contract is required; the product does not redistribute unlicensed data |

---

## 6. North-star workflow

1. The user selects a company and an **as-of timestamp**.
2. The system shows available filings, facts, evidence coverage, and freshness.
3. The user asks a question in natural language or starts from a research template.
4. A query planner selects lexical, vector, financial-fact, table, graph, and time-series retrieval lanes.
5. The Search Observatory streams candidates, filters, scores, and reranking decisions.
6. The answer is composed as atomic claims with claim-level citations.
7. The user sends evidence to the Extraction Studio.
8. Extraction agents propose normalized facts, guidance, KPIs, and causal drivers.
9. Deterministic validators check units, periods, duplicates, accounting identities, and schema constraints.
10. The user approves or edits extracted values.
11. Approved drivers populate a visual revenue model.
12. The Forecast Lab compares baselines, scenarios, and historical analogues.
13. The user exports a brief containing evidence, assumptions, calculations, uncertainty, and cutoff metadata.

---

## 7. Information architecture

### 7.1 Global navigation

- **Home:** recent workspaces, alerts, ingestion health.
- **Universe:** companies, sectors, watchlists, embedding atlas.
- **Research:** question answering, search observatory, document reader.
- **Extract:** agent runs, review queues, normalized facts.
- **Model:** revenue-driver graph, statements, scenarios, sensitivities.
- **Forecast:** models, backtests, analogues, uncertainty.
- **Audit:** citations, lineage, data quality, evaluation.
- **Settings:** providers, data sources, permissions, retention.

### 7.2 Persistent context bar

Every analytical screen shows:

- entity/company;
- selected documents or corpus;
- as-of timestamp;
- fiscal calendar;
- currency and display scale;
- active scenario;
- data freshness; and
- workspace collaborators.

Changing the as-of timestamp must invalidate or recompute downstream results that would otherwise include future information.

---

## 8. Experience specifications

### 8.1 Universe and Embedding Atlas

The Embedding Atlas is a GPU-rendered, zoomable projection of passages, facts, events, or companies.

#### Interactions

- Pan, zoom, search, filter, lasso, pin, compare, and animate through time.
- Color by topic, company, document type, fiscal period, or sentiment.
- Size by retrieval frequency, novelty, materiality, or user-defined metric.
- Select a point to show source text, nearest neighbors, metadata, and distance.
- Lasso a cluster to summarize, label, save as a collection, or compare with another cluster.
- Place the query embedding on the map and animate its nearest-neighbor expansion.
- Toggle between document-, passage-, fact-, and company-level projections.

#### Required disclosure

The interface must state that UMAP/t-SNE or similar two-dimensional projections distort global and local distances. Exact nearest-neighbor scores remain available in the detail panel.

#### Acceptance criteria

- `UX-ATL-001`: Render 100,000 projected points at p95 >= 30 frames per second on the reference client defined in Section 16.1.
- `UX-ATL-002`: Clicking a point opens source evidence in two interactions or fewer.
- `UX-ATL-003`: Filters update the visible set without reloading the page.
- `UX-ATL-004`: Projection method, parameters, corpus version, and embedding model are recorded.
- `UX-ATL-005`: A keyboard-accessible table exposes the filtered point set and exact neighbor distances without requiring the projection.

### 8.2 Search Observatory

The Search Observatory is the default research surface. It combines an answer area, retrieval lanes, evidence reader, and trace timeline.

#### Retrieval lanes

- dense vector search;
- lexical/full-text search;
- XBRL fact lookup;
- table/row retrieval;
- entity-event graph traversal;
- time-series analogue retrieval; and
- optional external/web evidence.

#### Visual trace

For each query display:

- parsed intent and entities;
- generated query variants;
- selected retrieval lanes;
- active metadata and time filters;
- candidates from each lane;
- normalized scores;
- fusion and reranking results;
- accepted and rejected context;
- token/context budget; and
- final claim-to-citation connections.

#### Interaction controls

- Toggle retrieval lanes on/off and rerun.
- Adjust top-k and time scope within permitted bounds.
- Compare two retrieval configurations.
- Mark evidence relevant, irrelevant, duplicate, or temporally invalid.
- Pin evidence into the current workspace.
- Open the surrounding filing section, table, or transcript turn.

#### Acceptance criteria

- `UX-SRC-001`: Every factual answer sentence is decomposed into one or more claims.
- `UX-SRC-002`: Every factual claim has a source span or is labeled “unsupported.”
- `UX-SRC-003`: Source snippets show document title, filing type, accession, section, publication time, and fiscal period.
- `UX-SRC-004`: The user can inspect why a retrieved candidate was rejected.
- `UX-SRC-005`: Re-running an immutable query version reproduces its inputs and trace.

### 8.3 Evidence Reader

The reader synchronizes rendered document content with extracted text, tables, XBRL facts, and citations.

#### Features

- Filing outline and section navigation.
- Side-by-side period comparison.
- Highlight citations used by answers, extractions, and assumptions.
- Display raw source, normalized value, unit, scale, and dimensions.
- Show amendments and restatements.
- Compare duplicated facts and flag inconsistent values.
- Add analyst notes without modifying source content.

### 8.4 Agentic Extraction Studio

The studio renders an execution graph and a review queue. Each agent has a typed input and output schema.

#### Initial agents

1. Document and section classifier.
2. Entity and product resolver.
3. Financial-fact and table extractor.
4. KPI definition and value extractor.
5. Management guidance extractor.
6. Revenue-driver mapper.
7. Risk and contradiction detector.
8. Period, unit, currency, and scale normalizer.
9. Accounting and schema validator.
10. Citation verifier.

#### Agent constraints

- Agents cannot silently overwrite approved facts.
- Every output includes evidence spans, confidence, schema version, model version, and run ID.
- Tools are explicitly allowlisted by agent role.
- Retries and fallbacks are bounded.
- Calculations execute in deterministic code.
- Extractions with calibrated confidence below `0.85`, any field-level confidence below `0.80`, any failed deterministic validation, or any conflicting source enter human review.
- Auto-approval is disabled for monetary facts, management guidance, and model assumptions in the MVP regardless of confidence.

#### Review queue

Reviewers can accept, edit, reject, merge, or request rerun. Edits record old value, new value, reviewer, reason, and timestamp.

#### Acceptance criteria

- `EXT-001`: A normalized numeric fact cannot be approved without period, unit, scale, source span, and entity.
- `EXT-002`: Guidance preserves whether it is point, range, floor, ceiling, or qualitative.
- `EXT-003`: Conflicting extractions are never silently collapsed.
- `EXT-004`: All approved outputs are versioned and immutable; corrections create new versions.
- `EXT-005`: Confidence thresholds are configurable only by an organization administrator and changes are audited.

### 8.5 Revenue Model Composer

The composer is a node-based causal graph backed by a deterministic calculation engine.

#### Node types

- source fact;
- analyst assumption;
- operational driver;
- formula;
- aggregation;
- scenario override;
- forecast model output;
- validation check; and
- reported financial output.

#### Required visualizations

- driver tree;
- historical/forecast line chart;
- price-volume-mix bridge;
- segment and geography treemap;
- revenue and gross-profit waterfall;
- scenario comparison;
- two-variable sensitivity heatmap;
- tornado chart; and
- probability distribution where simulations are enabled.

#### Formula engine

- Formulas are parsed into an abstract syntax tree.
- Cycles are rejected unless explicitly modeled as iterative calculations.
- Units and dimensions are checked.
- Each output stores dependency IDs and calculation version.
- Scenario overrides are sparse layers over a shared base model.
- The model supports quarterly and annual periods in the MVP.

#### Acceptance criteria

- `MOD-001`: Editing a driver updates all downstream values and coordinated charts.
- `MOD-002`: Each modeled cell can show its formula, dependencies, assumptions, and citations.
- `MOD-003`: Scenario changes do not mutate historical reported values.
- `MOD-004`: Model versions can be diffed and restored.

### 8.6 Forecast Lab

The Forecast Lab compares approaches rather than treating an LLM response as a forecast.

#### MVP forecast lanes

- naive last-value and seasonal baselines;
- analyst driver model;
- configurable statistical model;
- retrieved historical analogues; and
- ensemble of approved models.

#### MVP forecast contract

- Targets: quarterly revenue, ARR where disclosed, and gross profit.
- Frequency: fiscal quarter; annual values are derived from reported or forecast quarters.
- Horizons: one to eight fiscal quarters, with one-to-four-quarter accuracy reported separately from five-to-eight-quarter accuracy.
- Training window: at least twelve available quarters when the issuer has sufficient history; otherwise the lane must abstain or disclose the shorter window.
- Market features: adjusted close, total-return proxy where supported, volume, and corporate-action adjustments supplied by the configured bring-your-own adapter.
- Macroeconomic features: only explicitly selected, vintage-aware FRED series.
- Default intervals: 50%, 80%, and 95% prediction intervals.

LLMs may extract drivers, classify regimes, explain differences, and propose scenario narratives. They may not directly write authoritative forecast values without passing through a registered model or explicit analyst assumption.

#### Forecast output

- point forecast and prediction interval;
- bull/base/bear scenarios;
- historical backtest and rolling-origin error;
- error by forecast horizon;
- assumptions and feature/driver contributions;
- retrieved analogues and similarity rationale;
- data cutoff and training window; and
- model/version identifiers.

#### Metrics

Use metrics appropriate to the target:

- MAE and RMSE for level error;
- MAPE or sMAPE only where denominator behavior is acceptable;
- directional accuracy where explicitly useful;
- interval coverage and width; and
- calibration by forecast horizon.

#### Acceptance criteria

- `FOR-001`: Every forecast has an as-of timestamp and prevents future evidence leakage.
- `FOR-002`: The UI displays at least one naive baseline next to any advanced model.
- `FOR-003`: Backtests use rolling or expanding windows and preserve publication-time availability.
- `FOR-004`: Forecast exports distinguish reported, modeled, and user-supplied values.
- `FOR-005`: A forecast run fails closed when market-price adjustments or publication timestamps required by its registered feature contract are missing.

### 8.7 Audit and export

#### Audit graph

The audit view traverses:

`source -> source span -> extracted fact -> normalized fact -> assumption -> formula -> forecast -> claim -> export`

#### Export formats

- Markdown research brief;
- PDF brief;
- CSV/XLSX model tables;
- JSON evidence bundle; and
- reproducible workspace manifest.

The manifest includes corpus IDs, document hashes, model and prompt versions, retrieval configuration, cutoff time, agent runs, approvals, model version, and export time.

---

## 9. Functional requirements

### 9.1 Workspaces and access

- `FR-WRK-001`: Users can create, clone, archive, and restore workspaces.
- `FR-WRK-002`: A workspace has one default entity, base currency, fiscal calendar, and as-of timestamp.
- `FR-WRK-003`: Roles are owner, editor, reviewer, and viewer.
- `FR-WRK-004`: Comments and approvals are attributed to authenticated users.

### 9.2 Ingestion

- `FR-ING-001`: Ingest SEC submissions, filing documents, and company facts.
- `FR-ING-002`: Preserve source URLs, accessions, hashes, MIME types, and timestamps.
- `FR-ING-003`: Parsing is idempotent and versioned.
- `FR-ING-004`: Store raw, parsed, normalized, and indexed states separately.
- `FR-ING-005`: Reprocessing does not destroy prior versions.
- `FR-ING-006`: Respect source rate limits and identify the application in requests.
- `FR-ING-007`: Detect and quarantine malformed documents.
- `FR-ING-008`: Ingest adjusted price, volume, and corporate-action data through an organization-configured provider adapter without redistributing provider data across tenants.

### 9.3 Retrieval and answers

- `FR-RAG-001`: Support dense, lexical, structured-fact, table, and graph retrieval.
- `FR-RAG-002`: Apply entity, document type, period, publication time, and source filters before generation.
- `FR-RAG-003`: Support reciprocal rank fusion and pluggable rerankers.
- `FR-RAG-004`: Store full retrieval traces for evaluation and replay.
- `FR-RAG-005`: Generate answers as structured claims with citations.
- `FR-RAG-006`: Refuse or qualify answers when evidence is insufficient or contradictory.
- `FR-RAG-007`: Assign every claim one of `supported`, `partially_supported`, `contradicted`, `derived`, or `unsupported`.
- `FR-RAG-008`: A contradicted claim displays all material conflicting source spans and cannot be rendered as an unqualified conclusion.

### 9.4 Extraction

- `FR-EXT-001`: Extraction outputs validate against versioned JSON schemas.
- `FR-EXT-002`: Numeric outputs include sign, scale, unit, currency, period, and dimensions.
- `FR-EXT-003`: Users can approve or reject outputs individually or in bulk.
- `FR-EXT-004`: Approved facts can seed model nodes without re-entry.

### 9.5 Modeling and forecasting

- `FR-MOD-001`: Models support typed nodes and directed dependencies.
- `FR-MOD-002`: Calculations are reproducible server-side.
- `FR-MOD-003`: Users can create scenarios and compare them over coordinated views.
- `FR-FOR-001`: Forecast models implement a common fit/predict/backtest interface.
- `FR-FOR-002`: All forecast runs record dataset version and cutoff.

---

## 10. System architecture

### 10.1 Recommended implementation

Use a modular monolith for the MVP with asynchronous workers. This minimizes distributed-systems overhead while preserving clear service boundaries.

```text
Web client (Next.js/React/TypeScript)
  -> API/BFF (FastAPI/Python)
      -> application modules
         - identity/workspaces
         - ingestion
         - retrieval
         - extraction/agents
         - modeling
         - forecasting
         - audit/evaluation
      -> worker queue
      -> PostgreSQL + pgvector
      -> object storage
      -> analytical files (Parquet/Arrow)
      -> model/provider adapters
```

#### Frontend

- Next.js with React and TypeScript.
- React Flow for extraction and financial-driver graphs.
- Apache ECharts for financial charts, heatmaps, Sankey/flow, and high-volume canvas views.
- deck.gl for the embedding atlas and large point clouds.
- TanStack Query for server state.
- Zustand or equivalent for local interaction state.
- Web Workers and optional DuckDB-Wasm for local filtering of large Arrow/Parquet result sets.

#### Backend

- FastAPI and Pydantic for typed APIs and extraction schemas.
- PostgreSQL for application, temporal, and audit data.
- pgvector for dense search; PostgreSQL full-text search for lexical retrieval.
- Redis-backed queue or a Postgres-native job queue for asynchronous ingestion and agent runs.
- S3-compatible object storage for immutable source documents, rendered pages, and exports.
- Polars/PyArrow for columnar transforms.

#### Deployment

- Multi-tenant, team-oriented SaaS deployment.
- Containerized services.
- Separate web, API, and worker processes.
- Managed PostgreSQL with pgvector.
- Object storage with versioning enabled.
- OIDC authentication and organization-scoped authorization from Milestone 0.
- Infrastructure as code for every shared environment from Milestone 0.
- Local Docker Compose remains a development environment, not the product deployment model.

### 10.2 Why hybrid retrieval

Dense embeddings capture semantic similarity but can miss exact accounting terminology, tickers, dates, and values. Lexical search is strong for exact terms. Structured retrieval is required for facts and tables. The system therefore fuses independent ranked lists and optionally reranks the combined candidates.

A configurable score can be represented as:

```text
score(d, q) =
    w_dense   * dense_similarity(d, q)
  + w_lexical * lexical_score(d, q)
  + w_time    * temporal_relevance(d, q)
  + w_entity  * entity_match(d, q)
  + w_quality * source_quality(d)
```

For rank fusion, default to reciprocal rank fusion:

```text
RRF(d) = sum_r 1 / (k + rank_r(d))
```

Weights, `k`, top-k, and reranker versions are stored with the retrieval trace.

### 10.3 Point-in-time correctness

Every evidence record carries at least:

- `published_at`: when the information became publicly available;
- `filed_at`: regulatory filing time, if applicable;
- `period_start` and `period_end`: economic period represented;
- `ingested_at`: system ingestion time; and
- `valid_from`/`valid_to`: version validity in the application.

A query with cutoff `T` may retrieve only evidence whose applicable public-availability timestamp is less than or equal to `T`. Backtests must use the same constraint.

---

## 11. Data model

### 11.1 Core entities

| Entity | Purpose | Important fields |
|---|---|---|
| `organizations` | Tenant boundary | id, name, policy |
| `users` | Identity | id, organization_id, role |
| `workspaces` | Analysis context | entity_id, as_of, currency, scenario_id |
| `entities` | Issuer/company/brand hierarchy | CIK, ticker, LEI, parent_id |
| `documents` | Immutable source metadata | accession, hash, source URL, published_at |
| `document_versions` | Parsed/rendered versions | parser_version, object keys, status |
| `sections` | Filing hierarchy | item, heading, parent_id, order |
| `passages` | Retrieval chunks | text, section_id, token_count, offsets |
| `embeddings` | Vector representations | object_id, model, dimensions, vector |
| `financial_facts` | Normalized facts | concept, value, unit, scale, period, dimensions |
| `tables` / `table_cells` | Structured tables | headers, row/column coordinates, spans |
| `events` | Company/market events | type, time, entities, evidence_ids |
| `queries` | Versioned user questions | text, cutoff, config, user_id |
| `retrieval_runs` | Search traces | lanes, candidates, scores, latency |
| `claims` | Atomic answer assertions | text, status, confidence |
| `citations` | Claim/evidence edges | claim_id, source_span_id, entailment status |
| `agent_runs` | Tool and model execution | agent, prompt, model, inputs, outputs, status |
| `extractions` | Proposed normalized records | schema, payload, confidence, review state |
| `model_nodes` | Driver graph nodes | type, unit, formula, provenance |
| `model_edges` | Dependencies | source_node, target_node, role |
| `model_versions` | Immutable model snapshots | parent_id, scenario, created_by |
| `forecast_runs` | Forecast metadata and output | target, horizon, cutoff, metrics, intervals |
| `audit_events` | Append-only activity | actor, action, object, before/after hashes |

### 11.2 Source spans

Citations reference a stable source span rather than free-form copied text:

```json
{
  "document_version_id": "uuid",
  "section_id": "uuid",
  "page": 42,
  "start_char": 1821,
  "end_char": 2064,
  "text_hash": "sha256:..."
}
```

### 11.3 Claim and citation states

Claims use this closed status set:

- `supported`: all material elements are directly supported by verified evidence;
- `partially_supported`: at least one material qualifier or component lacks support;
- `contradicted`: credible in-scope evidence materially conflicts with the claim;
- `derived`: the claim follows from deterministic calculations whose inputs are supported; or
- `unsupported`: no adequate in-scope evidence was found.

Citation edges use `entailed`, `partial`, `contradictory`, or `irrelevant`. Generation confidence is not treated as evidence confidence. A claim may be displayed as a factual conclusion only when it is `supported` or `derived`; other states require explicit visual qualification.

### 11.4 Normalized financial fact

```json
{
  "entity_id": "uuid",
  "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
  "label": "Revenue",
  "value": "1250000000",
  "unit": "USD",
  "scale": 0,
  "period": {
    "type": "duration",
    "start": "2026-01-01",
    "end": "2026-03-31"
  },
  "dimensions": {},
  "source_span_id": "uuid",
  "reported_or_derived": "reported",
  "confidence": 1.0
}
```

Use decimal arithmetic for financial values. Do not store authoritative monetary values as binary floating-point numbers.

---

## 12. Ingestion and indexing pipeline

### 12.1 Sources

#### MVP

- SEC submissions API;
- SEC company facts/XBRL data;
- filing HTML and Inline XBRL;
- FRED macro series where configured; and
- adjusted price, volume, and corporate-action data supplied through a bring-your-own provider adapter.

#### Later

- licensed transcripts and news;
- investor presentations;
- bundled or redistributed market-price datasets beyond the bring-your-own adapter;
- international filing systems; and
- customer-owned research repositories.
- general PDF and user-upload ingestion.

### 12.2 Pipeline stages

1. Discover source and record metadata.
2. Download immutable raw bytes.
3. Hash and deduplicate.
4. Detect type and validate.
5. Parse HTML/iXBRL/PDF/tabular content.
6. Reconstruct document hierarchy.
7. Extract tables and source spans.
8. Normalize XBRL facts and entity identifiers.
9. Chunk by disclosure structure.
10. Generate embeddings.
11. Build lexical, vector, structured, and graph indexes.
12. Run quality checks.
13. Publish a corpus version atomically.

### 12.3 Chunking strategy

- Respect filing item, section, paragraph, list, and table boundaries.
- Preserve heading path and surrounding context.
- Avoid splitting a table from its title and headers.
- Create separate representations for passage text, table summaries, rows, and structured facts.
- Link repeated or overlapping chunks to one canonical source span.
- Store token counts per supported model family.

### 12.4 Idempotency

The job key is derived from source hash, parser version, normalizer version, chunker version, and embedding model. Re-running an identical job returns the prior result. Changing any version creates a new derived artifact without mutating the source.

---

## 13. Retrieval and generation pipeline

### 13.1 Query planning

The planner produces a typed plan:

```json
{
  "intent": "driver_analysis",
  "entities": ["uuid"],
  "periods": ["FY2025", "Q1-2026"],
  "cutoff": "2026-05-08T16:30:00Z",
  "lanes": ["lexical", "dense", "facts", "tables"],
  "filters": {
    "forms": ["10-K", "10-Q", "8-K"]
  },
  "answer_schema": "driver_analysis.v1"
}
```

### 13.2 Retrieval sequence

1. Parse entities, periods, concepts, and intent.
2. Resolve ambiguity before high-cost retrieval when necessary.
3. Generate bounded query variants.
4. Execute selected lanes concurrently.
5. Apply point-in-time and permission filters.
6. Deduplicate by source span and canonical fact.
7. Fuse ranked lists.
8. Rerank against the original question.
9. Diversify context across source, period, and viewpoint.
10. Assemble context within budget.
11. Generate structured claims.
12. Verify citations and numerical consistency.
13. Return answer plus trace.

### 13.3 Citation verification

For every claim:

- verify that cited text entails or directly supports the claim;
- verify that any number matches source value, unit, period, and sign;
- detect citations that merely mention the entity without supporting the assertion;
- label derived claims and include calculation lineage; and
- downgrade or remove claims whose support fails.

---

## 14. Agent orchestration

### 14.1 Execution model

Use a state machine or durable workflow per task. Avoid unconstrained agent-to-agent conversation.

Each step declares:

- input/output schema;
- permitted tools;
- maximum attempts and cost;
- timeout;
- retry policy;
- human-review rule; and
- audit payload.

### 14.2 Failure handling

- Tool timeout: retry with exponential backoff within a bounded budget.
- Schema failure: one repair attempt, then review queue.
- Conflicting sources: preserve alternatives and request review.
- Missing evidence: abstain or ask for additional corpus scope.
- Calculation failure: stop downstream model publication.
- Provider failure: use an approved fallback only if outputs remain comparable and versioned.

### 14.3 Prompt-injection defenses

Documents are untrusted data. The agent runtime must:

- separate system instructions from retrieved content;
- mark retrieved content as data, not executable instruction;
- prevent documents from changing tool permissions;
- validate all tool arguments;
- restrict outbound network destinations;
- avoid rendering unsanitized HTML; and
- log attempted instruction override patterns.

---

## 15. API specification

Use REST for commands and stable resources, Server-Sent Events for streamed runs, and signed object URLs for large artifacts. GraphQL can be reconsidered after the domain stabilizes.

### 15.1 Representative endpoints

#### Entities and evidence

- `GET /v1/entities?query=`
- `GET /v1/entities/{id}`
- `GET /v1/entities/{id}/documents`
- `GET /v1/documents/{id}`
- `GET /v1/documents/{id}/sections`
- `GET /v1/source-spans/{id}`

#### Ingestion

- `POST /v1/ingestion/jobs`
- `GET /v1/ingestion/jobs/{id}`
- `GET /v1/ingestion/jobs/{id}/events`

#### Research

- `POST /v1/workspaces/{id}/queries`
- `GET /v1/queries/{id}`
- `GET /v1/queries/{id}/events`
- `GET /v1/retrieval-runs/{id}`
- `POST /v1/retrieval-runs/{id}/feedback`

#### Extraction

- `POST /v1/workspaces/{id}/extraction-runs`
- `GET /v1/extraction-runs/{id}/events`
- `PATCH /v1/extractions/{id}/review`

#### Models and forecasts

- `POST /v1/workspaces/{id}/models`
- `POST /v1/models/{id}/versions`
- `GET /v1/model-versions/{id}/lineage`
- `POST /v1/model-versions/{id}/calculate`
- `POST /v1/model-versions/{id}/forecast-runs`
- `GET /v1/forecast-runs/{id}`

#### Audit and export

- `GET /v1/workspaces/{id}/audit-events`
- `GET /v1/claims/{id}/lineage`
- `POST /v1/workspaces/{id}/exports`

### 15.2 Error format

```json
{
  "error": {
    "code": "TEMPORAL_SCOPE_VIOLATION",
    "message": "Evidence was published after the workspace cutoff.",
    "details": {},
    "request_id": "uuid"
  }
}
```

### 15.3 Idempotency and concurrency

- Mutating endpoints accept an `Idempotency-Key` header.
- Versioned resources use optimistic concurrency with ETags or version numbers.
- Long-running operations return a run ID immediately.

---

## 16. Non-functional requirements

### 16.1 Performance targets

Targets are measured at p95 with 25 concurrent active users against a reference corpus of 100 B2B SaaS issuers, eight years of SEC filings and XBRL facts, 10 million passages, and 15 million embeddings. The reference server is 8 vCPU/32 GB RAM for API and workers plus managed PostgreSQL with 8 vCPU/32 GB RAM. The reference client is a current-generation desktop with 8 logical CPU cores, 16 GB RAM, hardware WebGL2, and a 50 Mbps connection with 50 ms round-trip latency. CI load tests may use proportionally scaled fixtures but release-candidate testing uses the reference profile.

| Operation | Target |
|---|---:|
| Workspace/document metadata | < 500 ms |
| Filtered lexical/vector retrieval | < 1.5 s |
| First streamed retrieval event | < 1 s |
| Initial cited answer | < 12 s and complete answer < 30 s |
| Model recalculation, 5k nodes | < 500 ms |
| Coordinated chart update | < 150 ms after data arrival |

The service-level objective is 99.5% monthly availability for the MVP, excluding announced maintenance. At least 99% of asynchronous jobs must complete or reach a terminal, actionable failure state within their documented timeout.

### 16.2 Reliability

- No source or approved record is destructively overwritten.
- Jobs are resumable after worker restart.
- Corpus publication is atomic.
- Daily backups and tested restore procedures are required before production.
- External provider failures degrade individual capabilities rather than corrupting state.

### 16.3 Accessibility

- Meet WCAG 2.2 AA for primary workflows.
- All charts have keyboard access and tabular/text alternatives.
- Color is never the only encoding.
- Graph nodes and edges are navigable and describable by assistive technology.
- Motion and animated projections respect reduced-motion preferences.

### 16.4 Browser support

Latest two stable versions of Chrome, Safari, Firefox, and Edge. The atlas may reduce point count or detail on unsupported GPU configurations.

---

## 17. Security, privacy, and governance

### 17.1 Security controls

- OIDC authentication and organization-scoped authorization.
- Row-level tenant isolation.
- Encryption in transit and at rest.
- Secrets in a managed secret store.
- Signed, expiring object-storage URLs.
- Append-only audit events for privileged operations.
- Dependency and container scanning in CI.
- Input validation and output sanitization.
- Egress allowlists for agent tools.
- Rate and cost limits per tenant, user, and provider.

### 17.2 Data governance

- Record license and redistribution policy per source.
- Do not ingest licensed analyst research or transcripts without explicit rights.
- Reserve deletion semantics for post-MVP customer uploads; no general uploads are accepted in the MVP.
- Separate customer content from evaluation/training datasets by default.
- Default query and model-run retention is 365 days; audit metadata and approved artifact lineage are retained for seven years unless an organization policy requires a shorter lawful period.
- Provider-derived market data follows the provider license and is deleted within 30 days after adapter disconnection unless retention rights explicitly permit otherwise.

### 17.3 Financial-product controls

- Prominent research-support disclaimer.
- Separate facts, derived calculations, analyst assumptions, and model-generated estimates visually and in exports.
- No brokerage actions in the MVP.
- Point-in-time cutoffs and restatements are explicit.
- User-visible methodology for forecasts and confidence intervals.

---

## 18. Observability and cost controls

### 18.1 Telemetry

Trace a user action across query planning, retrieval lanes, reranking, generation, citation verification, agent tools, model calculation, and export.

Capture:

- latency by stage;
- candidate and context counts;
- token and model usage;
- provider cost estimates;
- cache hit rate;
- retrieval and citation quality;
- extraction review outcomes;
- ingestion failure categories; and
- forecast evaluation metrics.

### 18.2 Budget controls

- Display an estimate before any run expected to cost more than USD 1.00.
- Default soft limits are USD 10 per user per day and USD 500 per organization per month; default hard limits are USD 25 per user per day and USD 1,000 per organization per month.
- Standard research queries are capped at 4 query variants, 100 retrieved candidates per lane, 30 reranked candidates, 16 context passages, and 32,000 input tokens unless an administrator configures lower limits.
- A standard research query has a USD 0.25 hard cost ceiling and 60-second wall-clock timeout; extraction batches and forecast jobs use separately displayed, administrator-approved budgets.
- Caching keyed by immutable inputs and model versions.
- Batch embeddings and background ingestion.
- Automatic downgrade or stop behavior must be explicit, configurable, and audited.
- Crossing a soft limit warns the user; crossing a hard limit stops new billable runs rather than silently switching models or incurring overage.

---

## 19. Evaluation strategy

Evaluation is a product feature, not a launch-only activity.

### 19.1 Retrieval evaluation

- Recall@k and precision@k on labeled financial questions.
- Mean reciprocal rank and nDCG.
- Evidence diversity across periods and sources.
- Temporal-validity rate.
- Numeric-fact retrieval accuracy.
- Ablation tests for lexical, dense, fact, table, and reranking stages.

### 19.2 Answer and citation evaluation

- Claim correctness.
- Claim completeness.
- Citation entailment.
- Citation completeness.
- Numeric consistency for value, unit, period, sign, and scale.
- Abstention quality when evidence is missing.

### 19.3 Extraction evaluation

- Exact/normalized match by schema field.
- Precision, recall, and F1 for extracted records.
- Unit/period normalization accuracy.
- Review acceptance and edit rates.
- Conflict-detection recall.

### 19.4 Forecast evaluation

- Rolling-origin backtests with publication-time availability.
- Comparison with naive and seasonal baselines.
- Error and calibration by horizon, company, sector, and regime.
- Interval coverage.
- Performance before and after retrieved analogues.

### 19.5 Initial benchmark set

Create a versioned internal benchmark containing:

- exact fact lookup;
- filing-section retrieval;
- multi-period comparison;
- table reasoning;
- guidance extraction;
- revenue-driver extraction;
- contradiction detection;
- temporal cutoff traps;
- restatement handling; and
- insufficient-evidence cases.

The initial benchmark contains at least 300 adjudicated questions across at least 20 US-listed B2B SaaS issuers, including a minimum of 30 cases in each listed category. Two qualified reviewers adjudicate disagreements.

### 19.6 Release gates

A release candidate must meet all of the following on the frozen benchmark:

| Measure | Gate |
|---|---:|
| Temporal-validity rate | 100% |
| Numeric value/unit/period/sign/scale accuracy | >= 99.0% |
| Citation entailment precision | >= 95.0% |
| Citation completeness | >= 92.0% |
| Retrieval Recall@10 | >= 90.0% |
| Guidance extraction F1 | >= 90.0% |
| KPI/revenue-driver extraction F1 | >= 88.0% |
| Contradiction-detection recall | >= 90.0% |
| Unsupported-answer abstention precision | >= 95.0% |
| 80% forecast-interval empirical coverage | 75%–85% |

No release is promoted if any gate fails. Advanced forecasting models must also beat the seasonal-naive baseline on median MAE over the supported one-to-four-quarter horizon; otherwise the baseline remains the default.

---

## 20. Testing strategy

### 20.1 Test layers

- Unit tests for parsers, formulas, normalization, filters, and scoring.
- Property tests for units, periods, decimal arithmetic, and model graphs.
- Golden-file tests for representative filings and tables.
- Contract tests for external data and model adapters.
- Integration tests from ingestion through cited answer.
- End-to-end tests for the north-star workflow.
- Visual regression tests for high-value screens.
- Load tests for ingestion, retrieval, atlas rendering, and recalculation.
- Security tests for tenant isolation, prompt injection, SSRF, and unsafe HTML.

### 20.2 Required CI checks

- formatting and linting;
- static typing;
- unit/integration tests;
- database migrations on empty and representative databases;
- dependency and secret scanning;
- frontend accessibility checks; and
- a small deterministic RAG evaluation suite.

---

## 21. Delivery plan

Use milestone exit criteria rather than fixed calendar promises.

### Milestone 0 — Foundations

Deliver:

- repository and CI;
- local containerized development environment;
- authentication skeleton;
- PostgreSQL/pgvector schema;
- object storage abstraction;
- provider interfaces; and
- observability baseline.

Exit criteria: a developer can start the stack, run migrations/tests, and create a workspace.

### Milestone 1 — SEC corpus and evidence reader

Deliver:

- entity lookup;
- SEC submissions and filing ingestion;
- XBRL company-fact normalization;
- document hierarchy and source spans;
- evidence reader; and
- ingestion-quality dashboard.

Exit criteria: a supported company’s last eight quarters can be ingested idempotently and inspected with stable source spans.

### Milestone 2 — Observable hybrid retrieval

Deliver:

- lexical and dense indexes;
- fact and table retrieval;
- query planner;
- rank fusion/reranking;
- Search Observatory; and
- structured claims and citations; and
- production Embedding Atlas with accessible table fallback.

Exit criteria: benchmark questions meet retrieval and citation thresholds with point-in-time filtering enabled.

### Milestone 3 — Agentic extraction

Deliver:

- extraction workflow runtime;
- KPI, guidance, revenue-driver, and normalization agents;
- deterministic validators;
- review queue; and
- approved fact registry.

Exit criteria: reviewers can trace, approve, correct, and version extractions without source ambiguity.

### Milestone 4 — Revenue model and scenarios

Deliver:

- typed model graph;
- calculation engine;
- scenarios;
- driver graph;
- coordinated financial charts; and
- lineage traversal.

Exit criteria: an approved extraction can seed a driver, recalculate downstream outputs, and retain complete provenance.

### Milestone 5 — Forecast Lab and audit export

Deliver:

- baseline and driver forecasts;
- rolling backtests;
- historical analogue retrieval;
- uncertainty visualization;
- audit graph; and
- Markdown/PDF/CSV/JSON exports.

Exit criteria: the north-star workflow is reproducible from cutoff to exported brief.

---

## 22. Initial backlog priorities

### P0

- Temporal evidence model and cutoff enforcement.
- Immutable source storage and stable spans.
- SEC/XBRL ingestion.
- Hybrid retrieval with trace.
- Claim-level citations.
- Decimal financial calculation engine.
- Human approval for extracted facts.
- Revenue driver graph and scenarios.
- Evaluation harness.
- Embedding Atlas and exact-neighbor detail view.

### P1

- Side-by-side filing change detection.
- Guidance-versus-actual tracking.
- Forecast analogue retrieval.
- Collaboration and model diffing.
- PDF/XLSX export.

### P2

- Broader source connectors.
- Portfolio-level analysis.
- International filings.
- Organization-specific taxonomies.
- Automated research alerts.

---

## 23. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Retrieval looks plausible but misses decisive evidence | Incorrect conclusions | Hybrid lanes, labeled evals, visible candidates, abstention |
| Look-ahead leakage | Invalid forecasts/backtests | Publication timestamps, cutoff filters, temporal tests |
| Incorrect units/periods | Material model errors | Typed facts, decimals, validators, approval queue |
| Filing parser drift | Missing or misplaced evidence | Golden filings, versioned parsers, quarantine and QA |
| Agent loops or excess cost | Poor reliability/economics | Bounded state machines, budgets, allowlisted tools |
| Visualization overstates embedding meaning | Misleading UX | Projection disclosure and exact-distance panel |
| Market/transcript licensing | Legal and product constraint | Source registry, BYO licensed providers, redistribution controls |
| pgvector scale/filter limitations | Retrieval degradation | Partitioning, filtered-index tests, iterative scans, migration interface |
| Forecasts interpreted as advice | Regulatory/reputation risk | Research framing, methodology, uncertainty, no trade execution |
| Provider lock-in | Cost and operational risk | Adapter interfaces and versioned provider contracts |

---

## 24. Product analytics

Measure whether the product improves auditable research, not simply chat volume.

### North-star metric

**Verified analytical artifacts completed per active analyst**, where an artifact contains at least one cited claim, approved extraction, or model output with complete lineage.

### Supporting metrics

- Time from question to accepted evidence.
- Percentage of factual claims with verified citations.
- Extraction acceptance/edit/rejection rate.
- Time to update a model after a new filing.
- Retrieval feedback rate and relevance.
- Reproducible export rate.
- Forecast performance against baseline.
- Cost per verified artifact.

Guardrails include unsupported-claim rate, temporal-violation rate, citation failure rate, ingestion error rate, and user-reported material-error rate.

---

## 25. Resolved decisions and bounded implementation choices

Product-scope decisions are resolved in Section 5.3. The following implementation choices may be decided through architecture decision records without changing MVP scope:

1. Default LLM, embedding, and reranking providers, provided they pass the same contracts, budgets, and release gates.
2. The first supported bring-your-own market-data adapter.
3. Redis-backed versus PostgreSQL-native job queue after a measured load test.
4. DuckDB-Wasm adoption; it may improve browser-side exploration but is not required to satisfy the MVP acceptance criteria.

Changing deployment model, financial-model depth, initial vertical, Atlas priority, or market-data licensing strategy requires a new specification version rather than an implementation ADR.

---

## 26. Definition of MVP done

The MVP is complete when a user can:

1. Select a supported company and historical as-of timestamp.
2. Ingest and inspect at least eight quarters of SEC filings and XBRL facts.
3. Ask a research question and inspect the hybrid retrieval trace.
4. Receive atomic claims with verified source spans.
5. Extract and approve at least one KPI, guidance item, and revenue driver.
6. Populate a visual revenue model without manually retyping the approved value.
7. Compare bull/base/bear forecasts with a naive baseline and uncertainty.
8. Trace a forecast output back through formulas and assumptions to evidence.
9. Export a reproducible research brief and evidence manifest.
10. Pass every numeric release gate in Section 19.6 plus the security, accessibility, performance, and reliability checks in Sections 16, 17, and 20.
11. Enforce the default cost ceilings and stop billable work at hard limits.

---

## 27. Research basis and primary references

### Financial and regulatory data

- [SEC EDGAR Application Programming Interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — submissions and extracted XBRL company facts.
- [SEC developer resources](https://www.sec.gov/about/developer-resources) — official access guidance.
- [FRED API overview](https://fred.stlouisfed.org/docs/api/fred/overview.html) — official macroeconomic data API.
- [XBRL Formula Rules tutorial](https://www.xbrl.org/guidance/xbrl-formula-rules-tutorial/) — executable validation rules.
- [XBRL Calculations 1.1 guidance](https://www.xbrl.org/guidance/adopting-calc1-1/) — duplicate facts and calculation consistency.

### Retrieval and finance research

- [pgvector](https://github.com/pgvector/pgvector) — vector search, HNSW/IVFFlat, hybrid search, and reranking guidance.
- [FinSrag / FinSeer](https://arxiv.org/abs/2502.05878) — retrieval tailored to financial time-series forecasting.
- [FinGEAR](https://arxiv.org/abs/2509.12042) — hierarchy- and terminology-aware retrieval over financial disclosures.
- [Point-in-Time Financial RAG](https://arxiv.org/abs/2605.31201) — event-, horizon-, and market-context-aware financial retrieval.

The research papers above are useful design inputs, not independent guarantees of production performance. All techniques must be evaluated against the application’s own point-in-time datasets and tasks.

### Visualization and implementation foundations

- [deck.gl](https://github.com/visgl/deck.gl) — GPU-powered large-scale visual exploration.
- [Apache ECharts](https://github.com/apache/echarts) — interactive browser charting.
- [React Flow / xyflow](https://github.com/xyflow/xyflow) — node-based interactive editors.
- [DuckDB-Wasm](https://github.com/duckdb/duckdb-wasm) — in-browser analytical SQL over Arrow, Parquet, CSV, and JSON.

### Existing profile context inspected

- [wilsonhj/Agentic-RAG-app](https://github.com/wilsonhj/Agentic-RAG-app) — existing React/FastAPI agentic RAG prototype. This specification retains the React/Python direction while adding finance-specific temporal, data-quality, retrieval, modeling, and provenance requirements.

---

## 28. Recommended repository structure for implementation

```text
.
├── apps/
│   ├── web/                 # Next.js/React application
│   └── api/                 # FastAPI application
├── workers/
│   ├── ingestion/
│   ├── extraction/
│   └── forecasting/
├── packages/
│   ├── contracts/           # OpenAPI/JSON schemas/generated clients
│   ├── calculation-engine/
│   ├── retrieval-evals/
│   └── ui/
├── db/
│   ├── migrations/
│   └── seeds/
├── evals/
│   ├── datasets/
│   ├── graders/
│   └── reports/
├── infra/
├── docs/
│   ├── architecture/
│   ├── decisions/
│   └── threat-model/
├── docker-compose.yml
├── Makefile
├── PLAN.md
├── TASKS.md
└── README.md
```

The first implementation commit should establish contracts, temporal semantics, and evaluation fixtures before building the conversational surface. These foundations are expensive to retrofit after data and user workflows accumulate.
