import { ENTITY_ID } from "../../fixtures/synthetic-filing";
import type { Candidate, QueryPlan, QuerySnapshot, RetrievalTrace } from "../query-source";
import type { RetrievalEvent } from "../sse";

// Fixture ids for the committed Observatory demo. The candidate span ids are
// real synthetic-filing spans so candidate -> reader links resolve end to end.
export const MOCK_WORKSPACE_ID = "dddddddd-0000-4000-8000-000000000001";
export const MOCK_QUERY_ID = "eeeeeeee-0000-4000-8000-000000000001";
export const MOCK_RUN_ID = "ffffffff-0000-4000-8000-000000000001";
export const MOCK_RERUN_ID = "ffffffff-0000-4000-8000-000000000002";
export const MOCK_CORPUS_VERSION_ID = "12121212-0000-4000-8000-000000000001";
export const MOCK_INDEX_VERSION_ID = "13131313-0000-4000-8000-000000000001";
export const DOC_10Q_VERSION_ID = "aaaaaaaa-0000-4000-8000-000000001001";
export const DOC_10QA_VERSION_ID = "aaaaaaaa-0000-4000-8000-000000001002";

const SPAN_REVENUE_STMT = "cccccccc-0000-4000-8000-000000000001";
const SPAN_REVENUE_MDA = "cccccccc-0000-4000-8000-000000000002";
const SPAN_SEGMENT_REVENUE = "cccccccc-0000-4000-8000-000000000005";
const SPAN_EPS_MDA = "cccccccc-0000-4000-8000-000000000004";
const SPAN_REVENUE_RESTATED = "cccccccc-0000-4000-8000-000000000007";

// Effective cutoff for this run. Candidates published after it must never be
// rendered as supported evidence.
export const MOCK_EFFECTIVE_AS_OF = "2026-06-30T23:59:59Z";
const WITHIN_CUTOFF = "2026-05-15T00:00:00Z";
const AFTER_CUTOFF = "2026-09-30T00:00:00Z";

const ITEM_REVENUE = "10101010-0000-4000-8000-000000000001";
const ITEM_REVENUE_MDA = "10101010-0000-4000-8000-000000000002";
const ITEM_SEGMENT = "10101010-0000-4000-8000-000000000003";
const ITEM_EPS_DUP = "10101010-0000-4000-8000-000000000004";
const ITEM_FUTURE = "10101010-0000-4000-8000-000000000005";
const ITEM_CROSS_VERSION = "10101010-0000-4000-8000-000000000006";

const MOCK_PLAN: QueryPlan = {
  schema_version: "query-plan/v1",
  intent: "fact_lookup",
  entity_ids: [ENTITY_ID],
  effective_as_of: MOCK_EFFECTIVE_AS_OF,
  corpus_version_id: MOCK_CORPUS_VERSION_ID,
  index_version_id: MOCK_INDEX_VERSION_ID,
  lanes: ["dense", "lexical", "facts", "tables"],
  variants: ["Q1 2026 total revenue", "first quarter 2026 net revenue"],
  filters: { forms: ["10-Q"], periods: ["2026-Q1"] },
  budgets: { lane_top_k: 25, fused_top_k: 10, context_items: 6, timeout_ms: 15000 },
};

const CANDIDATES: Candidate[] = [
  {
    item_id: ITEM_REVENUE,
    kind: "passage",
    contributions: [
      {
        lane: "dense",
        variant_index: 0,
        lane_rank: 1,
        raw_score: "0.8123",
        normalized_score: "0.97",
        rrf_contribution: "0.0164",
        timing_ms: 41,
      },
      {
        lane: "lexical",
        variant_index: 0,
        lane_rank: 2,
        raw_score: "12.44",
        normalized_score: "0.88",
        rrf_contribution: "0.0161",
        timing_ms: 12,
      },
    ],
    fused_score: "0.0325",
    fused_rank: 1,
    rerank_score: "0.9910",
    rerank_rank: 1,
    accepted: true,
    source_span_id: SPAN_REVENUE_STMT,
    document_version_id: DOC_10Q_VERSION_ID,
    published_at: WITHIN_CUTOFF,
  },
  {
    item_id: ITEM_REVENUE_MDA,
    kind: "passage",
    contributions: [
      {
        lane: "dense",
        variant_index: 1,
        lane_rank: 2,
        raw_score: "0.7710",
        normalized_score: "0.91",
        rrf_contribution: "0.0161",
        timing_ms: 41,
      },
    ],
    fused_score: "0.0161",
    fused_rank: 2,
    rerank_score: "0.9420",
    rerank_rank: 2,
    accepted: true,
    source_span_id: SPAN_REVENUE_MDA,
    document_version_id: DOC_10Q_VERSION_ID,
    published_at: WITHIN_CUTOFF,
  },
  {
    item_id: ITEM_SEGMENT,
    kind: "fact",
    contributions: [
      {
        lane: "facts",
        variant_index: 0,
        lane_rank: 1,
        raw_score: "1.0",
        normalized_score: "1.0",
        rrf_contribution: "0.0164",
        timing_ms: 8,
      },
    ],
    fused_score: "0.0164",
    fused_rank: 3,
    rerank_score: "0.7002",
    rerank_rank: 3,
    accepted: true,
    source_span_id: SPAN_SEGMENT_REVENUE,
    document_version_id: DOC_10Q_VERSION_ID,
    published_at: WITHIN_CUTOFF,
  },
  {
    item_id: ITEM_EPS_DUP,
    kind: "passage",
    contributions: [
      {
        lane: "lexical",
        variant_index: 0,
        lane_rank: 5,
        raw_score: "6.10",
        normalized_score: "0.44",
        rrf_contribution: "0.0154",
        timing_ms: 12,
      },
    ],
    fused_score: "0.0154",
    fused_rank: 4,
    rerank_score: null,
    rerank_rank: null,
    accepted: false,
    rejection_code: "dedupe_near_duplicate",
    decision_detail: { duplicate_of: ITEM_REVENUE_MDA },
    source_span_id: SPAN_EPS_MDA,
    document_version_id: DOC_10Q_VERSION_ID,
    published_at: WITHIN_CUTOFF,
  },
  {
    item_id: ITEM_FUTURE,
    kind: "passage",
    contributions: [
      {
        lane: "dense",
        variant_index: 0,
        lane_rank: 8,
        raw_score: "0.6001",
        normalized_score: "0.55",
        rrf_contribution: "0.0147",
        timing_ms: 41,
      },
    ],
    fused_score: "0.0147",
    fused_rank: 5,
    rerank_score: null,
    rerank_rank: null,
    // Published after the effective cutoff: filtered, and must never render as supported.
    accepted: false,
    rejection_code: "temporal_after_cutoff",
    source_span_id: SPAN_REVENUE_STMT,
    document_version_id: DOC_10Q_VERSION_ID,
    published_at: AFTER_CUTOFF,
  },
  {
    item_id: ITEM_CROSS_VERSION,
    kind: "passage",
    contributions: [
      {
        lane: "dense",
        variant_index: 0,
        lane_rank: 9,
        raw_score: "0.5900",
        normalized_score: "0.52",
        rrf_contribution: "0.0145",
        timing_ms: 41,
      },
    ],
    fused_score: "0.0145",
    fused_rank: 6,
    rerank_score: null,
    rerank_rank: null,
    // Belongs to a different document version than the run lineage: cross-version, never supported.
    accepted: false,
    rejection_code: "cross_version",
    source_span_id: SPAN_REVENUE_RESTATED,
    document_version_id: DOC_10QA_VERSION_ID,
    published_at: WITHIN_CUTOFF,
  },
];

const event = (
  seq: number,
  type: RetrievalEvent["type"],
  payload: Record<string, unknown> = {},
): RetrievalEvent => ({
  schema_version: "retrieval-event/v1",
  run_id: MOCK_RUN_ID,
  seq,
  type,
  occurred_at: new Date(Date.parse("2026-07-01T12:00:00Z") + seq * 100).toISOString(),
  payload,
});

/** Ordered persisted event log the mock stream replays (seq ascending). */
export const MOCK_EVENTS: RetrievalEvent[] = [
  event(1, "run_started"),
  event(2, "plan_ready", { lanes: MOCK_PLAN.lanes }),
  event(3, "lane_started", { lane: "dense" }),
  event(4, "candidate_batch", { lane: "dense", count: 8 }),
  event(5, "lane_completed", { lane: "dense" }),
  event(6, "lane_started", { lane: "lexical" }),
  event(7, "lane_completed", { lane: "lexical" }),
  event(8, "fusion_completed", { fused: 6 }),
  event(9, "rerank_completed", { reranked: 3 }),
  event(10, "context_selected", { context_items: 3 }),
  event(11, "claim_generated", { claim_id: "20202020-0000-4000-8000-000000000001" }),
  event(12, "citation_verified", { item_id: ITEM_REVENUE, status: "entailed" }),
  event(13, "run_completed", { status: "succeeded" }),
];

export const MOCK_TRACE: RetrievalTrace = {
  run_id: MOCK_RUN_ID,
  query_id: MOCK_QUERY_ID,
  status: "succeeded",
  plan: MOCK_PLAN,
  parent_run_id: null,
  lineage: {
    corpus_version_id: MOCK_CORPUS_VERSION_ID,
    index_version_id: MOCK_INDEX_VERSION_ID,
    planner_version: "planner@1.4.2",
    config_hash: "sha256:0f1e2d3c4b5a69788796a5b4c3d2e1f00112233445566778899aabbccddeeff0",
    embedding_provider: "voyage",
    embedding_model: "voyage-3-large",
    generation_provider: "anthropic",
    generation_model: "claude-opus-4-8",
  },
  events: MOCK_EVENTS,
  candidates: CANDIDATES,
  decisions: [
    {
      stage: "filter",
      code: "temporal_after_cutoff",
      item_ids: [ITEM_FUTURE],
      detail: { effective_as_of: MOCK_EFFECTIVE_AS_OF, published_at: AFTER_CUTOFF },
      occurred_at: "2026-07-01T12:00:01Z",
    },
    {
      stage: "filter",
      code: "cross_version",
      item_ids: [ITEM_CROSS_VERSION],
      detail: { lineage_version: DOC_10Q_VERSION_ID },
      occurred_at: "2026-07-01T12:00:01Z",
    },
    {
      stage: "dedupe",
      code: "dedupe_near_duplicate",
      item_ids: [ITEM_EPS_DUP],
      detail: { duplicate_of: ITEM_REVENUE_MDA, cosine: 0.982 },
      occurred_at: "2026-07-01T12:00:02Z",
    },
    {
      stage: "context",
      code: "context_budget_selected",
      item_ids: [ITEM_REVENUE, ITEM_REVENUE_MDA, ITEM_SEGMENT],
      occurred_at: "2026-07-01T12:00:03Z",
    },
  ],
  claims: [
    {
      id: "20202020-0000-4000-8000-000000000001",
      text: "Total revenue for Q1 2026 was $4,200 million.",
      status: "supported",
      citations: [
        {
          item_id: ITEM_REVENUE,
          source_span_id: SPAN_REVENUE_STMT,
          status: "entailed",
          numeric_checks: { revenue_value_matches: true },
        },
      ],
    },
    {
      id: "20202020-0000-4000-8000-000000000002",
      text: "Segment revenue growth was driven primarily by the cloud segment.",
      status: "partially_supported",
      citations: [
        {
          item_id: ITEM_SEGMENT,
          source_span_id: SPAN_SEGMENT_REVENUE,
          status: "partial",
          numeric_checks: {},
        },
      ],
    },
    {
      id: "20202020-0000-4000-8000-000000000003",
      text: "Diluted EPS was restated downward in a later amendment.",
      status: "contradicted",
      citations: [
        {
          item_id: ITEM_REVENUE_MDA,
          source_span_id: SPAN_REVENUE_MDA,
          status: "contradictory",
          numeric_checks: { eps_value_matches: false },
        },
      ],
    },
  ],
  timings_ms: {
    plan: 22,
    retrieve: 61,
    fuse: 9,
    rerank: 74,
    context: 5,
    generate: 812,
    verify: 140,
  },
  budget_usage: { context_items: 3, context_tokens: 1840, input_tokens: 5210, output_tokens: 240 },
  cost_usd: "0.0421",
  started_at: "2026-07-01T12:00:00Z",
  finished_at: "2026-07-01T12:00:04Z",
};

export const MOCK_QUERY_SNAPSHOT: QuerySnapshot = {
  query_id: MOCK_QUERY_ID,
  parent_query_id: null,
  question: "What was total revenue for Q1 2026?",
  plan: MOCK_PLAN,
  runs: [
    {
      run_id: MOCK_RUN_ID,
      parent_run_id: null,
      status: "succeeded",
      mode: "execute",
      created_at: "2026-07-01T12:00:00Z",
    },
    {
      run_id: MOCK_RERUN_ID,
      parent_run_id: MOCK_RUN_ID,
      status: "succeeded",
      mode: "rerun",
      created_at: "2026-07-01T12:05:00Z",
    },
  ],
  created_at: "2026-07-01T12:00:00Z",
};
