import type { components } from "@fel/contracts";

/**
 * Canonical contract shapes consumed from @fel/contracts. The web app never
 * redefines these; it only aliases them and layers UI-side records (stable
 * ids, section view-models) on top.
 */
export type DocumentMeta = components["schemas"]["DocumentMeta"];
export type SourceSpan = components["schemas"]["SourceSpan"];

/**
 * Mirror of the frozen financial-fact contract
 * (packages/contracts/schemas/financial-fact.schema.json,
 * $id https://contracts.fel.dev/schemas/financial-fact/v1). The schema is not
 * part of the OpenAPI surface yet, so no generated TS type exists; this alias
 * is kept honest by apps/web/src/lib/fixtures/fixture.test.ts, which validates
 * every fixture fact against the canonical JSON Schema with ajv.
 *
 * TODO(contract-change): replace this hand-mirrored type with a generated one
 * once the financial-fact schema joins the OpenAPI surface in
 * packages/contracts (frozen for PR #79; needs a `contract-change` issue and
 * an accepted ADR). Deliberately NOT fixed here.
 */
export interface NormalizedFinancialFact {
  entity_id: string;
  concept: string;
  label?: string;
  /** Decimal string — monetary values are never binary floats (spec 11.4). */
  value: string;
  unit: string;
  scale: number;
  period: {
    type: "instant" | "duration";
    instant?: string;
    start?: string;
    end?: string;
  };
  dimensions?: Record<string, string>;
  source_span_id: string;
  reported_or_derived: "reported" | "derived";
  confidence?: number;
}

/** A source span keyed by the server-side span id (see GET /v1/source-spans/{sourceSpanId}). */
export interface SourceSpanRecord {
  id: string;
  span: SourceSpan;
}

/** A normalized fact keyed by a stable record id. */
export interface FinancialFactRecord {
  id: string;
  fact: NormalizedFinancialFact;
}

/**
 * UI view-model for an extracted filing section. Sections are referenced by
 * SourceSpan.section_id; span offsets are relative to `content`.
 */
export interface SectionRecord {
  id: string;
  document_version_id: string;
  parent_id?: string;
  order: number;
  /** 1 = top-level part, 2 = item, 3 = statement/note. */
  level: number;
  title: string;
  content: string;
}
