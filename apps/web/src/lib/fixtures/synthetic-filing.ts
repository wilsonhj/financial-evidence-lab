import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";

/**
 * Committed synthetic filing fixture conforming to @fel/contracts shapes.
 *
 * Meridian Instruments, Inc. (fictional) files a Q1 2026 Form 10-Q and later a
 * Form 10-Q/A restating net income. The fixture deliberately contains:
 *
 * - a duplicate fact pair with CONFLICTING values (revenue: $1,250.0M in the
 *   statements vs $1,243.0M repeated in MD&A) — flagged as inconsistent;
 * - a duplicate fact pair with CONSISTENT values (diluted EPS $0.52 in both
 *   the statements and MD&A);
 * - an amendment/restatement (net income $86.4M restated to $79.5M in the
 *   10-Q/A) linking the two document versions;
 * - a dimensioned fact (Instruments segment revenue).
 *
 * Span offsets are relative to their section's `content`; every text_hash is
 * the sha256 of the exact cited substring. fixture.test.ts recomputes offsets
 * and hashes and validates every fact against the frozen JSON Schema, so this
 * file cannot silently drift from the contracts.
 */

export const ENTITY_ID = "11111111-1111-4111-8111-111111111111";

export const DOC_10Q_ID = "aaaaaaaa-0000-4000-8000-000000000001";
export const DOC_10QA_ID = "aaaaaaaa-0000-4000-8000-000000000002";

export const fixtureDocuments: DocumentMeta[] = [
  {
    id: DOC_10Q_ID,
    entity_id: ENTITY_ID,
    form: "10-Q",
    accession: "0000111111-26-000123",
    source_url: "https://filings.example.test/meridian/0000111111-26-000123.htm",
    content_hash: "sha256:1e6a4b6d3d6f0d1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192",
    published_at: "2026-04-24T20:15:00Z",
    filed_at: "2026-04-24T20:15:00Z",
    period_start: "2026-01-01",
    period_end: "2026-03-31",
    ingested_at: "2026-04-25T02:00:00Z",
    valid_from: "2026-04-24T20:15:00Z",
    valid_to: "2026-06-12T21:05:00Z",
  },
  {
    id: DOC_10QA_ID,
    entity_id: ENTITY_ID,
    form: "10-Q/A",
    accession: "0000111111-26-000198",
    source_url: "https://filings.example.test/meridian/0000111111-26-000198.htm",
    content_hash: "sha256:9b8a7c6d5e4f30211203f4e5d6c7b8a99b8a7c6d5e4f30211203f4e5d6c7b8a9",
    published_at: "2026-06-12T21:05:00Z",
    filed_at: "2026-06-12T21:05:00Z",
    period_start: "2026-01-01",
    period_end: "2026-03-31",
    ingested_at: "2026-06-13T02:00:00Z",
    valid_from: "2026-06-12T21:05:00Z",
  },
];

const SEC_PART1 = "bbbbbbbb-0000-4000-8000-00000000a001";
const SEC_ITEM1 = "bbbbbbbb-0000-4000-8000-00000000a002";
const SEC_STATEMENTS = "bbbbbbbb-0000-4000-8000-00000000a003";
const SEC_NOTES = "bbbbbbbb-0000-4000-8000-00000000a004";
const SEC_MDA = "bbbbbbbb-0000-4000-8000-00000000a005";
const SEC_CONTROLS = "bbbbbbbb-0000-4000-8000-00000000a006";
const SEC_A_EXPLANATORY = "bbbbbbbb-0000-4000-8000-00000000b001";
const SEC_A_ITEM1 = "bbbbbbbb-0000-4000-8000-00000000b002";
const SEC_A_STATEMENTS = "bbbbbbbb-0000-4000-8000-00000000b003";

export const fixtureSections: SectionRecord[] = [
  {
    id: SEC_PART1,
    document_version_id: DOC_10Q_ID,
    order: 1,
    level: 1,
    title: "Part I — Financial Information",
    content:
      "This Quarterly Report on Form 10-Q covers the three months ended March 31, 2026. Part I presents the unaudited condensed consolidated financial statements of Meridian Instruments, Inc. and accompanying notes.",
  },
  {
    id: SEC_ITEM1,
    document_version_id: DOC_10Q_ID,
    parent_id: SEC_PART1,
    order: 2,
    level: 2,
    title: "Item 1. Financial Statements",
    content:
      "The condensed consolidated financial statements included in this Item 1 are unaudited and reflect all adjustments necessary for a fair statement of the interim periods presented.",
  },
  {
    id: SEC_STATEMENTS,
    document_version_id: DOC_10Q_ID,
    parent_id: SEC_ITEM1,
    order: 3,
    level: 3,
    title: "Condensed Consolidated Statements of Operations",
    content:
      "Amounts are presented in millions of U.S. dollars except per-share data. Revenue for the three months ended March 31, 2026 was $1,250.0 million, compared with $1,118.4 million in the prior-year period. Cost of revenue was $702.6 million. Net income was $86.4 million, or $0.52 per diluted share. Weighted-average diluted shares outstanding were 166.2 million.",
  },
  {
    id: SEC_NOTES,
    document_version_id: DOC_10Q_ID,
    parent_id: SEC_ITEM1,
    order: 4,
    level: 3,
    title: "Notes to Condensed Consolidated Financial Statements",
    content:
      "Note 3. Revenue disaggregation. Revenue from the Instruments segment was $812.0 million for the three months ended March 31, 2026, and revenue from the Services segment was $438.0 million. Segment results are reviewed quarterly by the chief operating decision maker.",
  },
  {
    id: SEC_MDA,
    document_version_id: DOC_10Q_ID,
    parent_id: SEC_PART1,
    order: 5,
    level: 2,
    title: "Item 2. Management's Discussion and Analysis",
    content:
      "Total revenue of $1,243.0 million for the quarter increased 11.2% year over year, driven by instrument shipments to industrial customers. We reported net income of $86.4 million, or $0.52 per diluted share, reflecting continued operating discipline.",
  },
  {
    id: SEC_CONTROLS,
    document_version_id: DOC_10Q_ID,
    parent_id: SEC_PART1,
    order: 6,
    level: 2,
    title: "Item 4. Controls and Procedures",
    content:
      "Management, with the participation of the principal executive officer and principal financial officer, evaluated the effectiveness of our disclosure controls and procedures as of March 31, 2026 and concluded they were effective.",
  },
  {
    id: SEC_A_EXPLANATORY,
    document_version_id: DOC_10QA_ID,
    order: 1,
    level: 1,
    title: "Explanatory Note",
    content:
      "This Amendment No. 1 on Form 10-Q/A amends the Quarterly Report on Form 10-Q for the three months ended March 31, 2026, originally filed on April 24, 2026. It restates the condensed consolidated statements of operations to correct the timing of revenue-related warranty accruals.",
  },
  {
    id: SEC_A_ITEM1,
    document_version_id: DOC_10QA_ID,
    order: 2,
    level: 2,
    title: "Item 1. Financial Statements (as restated)",
    content:
      "The restated condensed consolidated financial statements included in this Item 1 supersede the corresponding statements in the original filing.",
  },
  {
    id: SEC_A_STATEMENTS,
    document_version_id: DOC_10QA_ID,
    parent_id: SEC_A_ITEM1,
    order: 3,
    level: 3,
    title: "Condensed Consolidated Statements of Operations (restated)",
    content:
      "Amounts are presented in millions of U.S. dollars except per-share data. Revenue was unchanged at $1,250.0 million. As restated, net income for the three months ended March 31, 2026 was $79.5 million, or $0.48 per diluted share, reflecting an increase of $6.9 million in accrued warranty expense.",
  },
];

const SPAN_REVENUE_STMT = "cccccccc-0000-4000-8000-000000000001";
const SPAN_REVENUE_MDA = "cccccccc-0000-4000-8000-000000000002";
const SPAN_NET_INCOME_STMT = "cccccccc-0000-4000-8000-000000000003";
const SPAN_EPS_MDA = "cccccccc-0000-4000-8000-000000000004";
const SPAN_SEGMENT_REVENUE = "cccccccc-0000-4000-8000-000000000005";
const SPAN_NET_INCOME_RESTATED = "cccccccc-0000-4000-8000-000000000006";
const SPAN_REVENUE_RESTATED = "cccccccc-0000-4000-8000-000000000007";

export const fixtureSpans: SourceSpanRecord[] = [
  {
    id: SPAN_REVENUE_STMT,
    span: {
      document_version_id: DOC_10Q_ID,
      section_id: SEC_STATEMENTS,
      page: 4,
      start_char: 73,
      end_char: 201,
      text_hash: "sha256:d0c91586447d18fe6ab7d92ccfdba9a9c0ba06cd798684838317fcae61b754fb",
    },
  },
  {
    id: SPAN_NET_INCOME_STMT,
    span: {
      document_version_id: DOC_10Q_ID,
      section_id: SEC_STATEMENTS,
      page: 4,
      start_char: 238,
      end_char: 295,
      text_hash: "sha256:b9f093265b2593efd5e27845cf185ab04a9839aea93edc8164435efe30c8cf18",
    },
  },
  {
    id: SPAN_SEGMENT_REVENUE,
    span: {
      document_version_id: DOC_10Q_ID,
      section_id: SEC_NOTES,
      page: 9,
      start_char: 32,
      end_char: 129,
      text_hash: "sha256:af97a10ce99fcd5be0f68ef9b61187104cac6f119a6b46b033efda8aa4f1d04c",
    },
  },
  {
    id: SPAN_REVENUE_MDA,
    span: {
      document_version_id: DOC_10Q_ID,
      section_id: SEC_MDA,
      page: 18,
      start_char: 0,
      end_char: 80,
      text_hash: "sha256:8dee481a3be8bc1abad39a867b568cfb3b3150ebbaf2866f1490641c855ef021",
    },
  },
  {
    id: SPAN_EPS_MDA,
    span: {
      document_version_id: DOC_10Q_ID,
      section_id: SEC_MDA,
      page: 18,
      start_char: 138,
      end_char: 205,
      text_hash: "sha256:03a491c2a06d5f69b6c58c1b3f6121681ad05d91674194d7a111497de2d99002",
    },
  },
  {
    id: SPAN_REVENUE_RESTATED,
    span: {
      document_version_id: DOC_10QA_ID,
      section_id: SEC_A_STATEMENTS,
      page: 3,
      start_char: 73,
      end_char: 115,
      text_hash: "sha256:61ba46c5e1165be54a911ae27c05f14163e3f2e48c211cecfdb7b6f0217380b1",
    },
  },
  {
    id: SPAN_NET_INCOME_RESTATED,
    span: {
      document_version_id: DOC_10QA_ID,
      section_id: SEC_A_STATEMENTS,
      page: 3,
      start_char: 116,
      end_char: 227,
      text_hash: "sha256:97b9d4abbb7f0babf169ea25079df7bd9d665227ed5d7a7800c7e878af997f4c",
    },
  },
];

const Q1_2026 = { type: "duration", start: "2026-01-01", end: "2026-03-31" } as const;

export const fixtureFacts: FinancialFactRecord[] = [
  {
    id: "dddddddd-0000-4000-8000-000000000001",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
      label: "Revenue",
      value: "1250",
      unit: "USD",
      scale: 6,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_REVENUE_STMT,
      reported_or_derived: "reported",
      confidence: 1.0,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000002",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
      label: "Revenue",
      value: "1243000000",
      unit: "USD",
      scale: 0,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_REVENUE_MDA,
      reported_or_derived: "reported",
      confidence: 0.94,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000003",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:NetIncomeLoss",
      label: "Net income",
      value: "86.4",
      unit: "USD",
      scale: 6,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_NET_INCOME_STMT,
      reported_or_derived: "reported",
      confidence: 1.0,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000004",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:EarningsPerShareDiluted",
      label: "Diluted EPS",
      value: "0.52",
      unit: "USD/share",
      scale: 0,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_NET_INCOME_STMT,
      reported_or_derived: "reported",
      confidence: 1.0,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000005",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:EarningsPerShareDiluted",
      label: "Diluted EPS",
      value: "0.52",
      unit: "USD/share",
      scale: 0,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_EPS_MDA,
      reported_or_derived: "reported",
      confidence: 0.9,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000006",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
      label: "Revenue — Instruments segment",
      value: "812",
      unit: "USD",
      scale: 6,
      period: Q1_2026,
      dimensions: { segment: "Instruments" },
      source_span_id: SPAN_SEGMENT_REVENUE,
      reported_or_derived: "reported",
      confidence: 0.97,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000007",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:NetIncomeLoss",
      label: "Net income (restated)",
      value: "79.5",
      unit: "USD",
      scale: 6,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_NET_INCOME_RESTATED,
      reported_or_derived: "reported",
      confidence: 1.0,
    },
  },
  {
    id: "dddddddd-0000-4000-8000-000000000008",
    fact: {
      entity_id: ENTITY_ID,
      concept: "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
      label: "Revenue (restated filing)",
      value: "1250000000",
      unit: "USD",
      scale: 0,
      period: Q1_2026,
      dimensions: {},
      source_span_id: SPAN_REVENUE_RESTATED,
      reported_or_derived: "reported",
      confidence: 1.0,
    },
  },
];
