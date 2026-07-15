import type { components } from "@fel/contracts";

/**
 * Canonical contract shapes consumed from @fel/contracts. The web app never
 * redefines these; it only aliases them and layers UI-side records (stable
 * ids, section view-models) on top.
 */
export type DocumentMeta = components["schemas"]["DocumentMeta"];
export type SourceSpan = components["schemas"]["SourceSpan"];
export type NormalizedFinancialFact = components["schemas"]["FinancialFact"];
export type SourceSpanRecord = components["schemas"]["ReaderSpanRecord"];
export type ReaderResponse = components["schemas"]["ReaderResponse"];
export type ReaderDocument = components["schemas"]["ReaderDocument"];
export type ReaderSibling = components["schemas"]["ReaderSibling"];
export type ReaderSection = components["schemas"]["ReaderSection"];
export type ReaderFactRecord = components["schemas"]["ReaderFactRecord"];

/** The generated reader fact wrapper, including required version provenance. */
export type FinancialFactRecord = ReaderFactRecord;

/**
 * UI view-model for an extracted filing section. Sections are referenced by
 * SourceSpan.section_id.
 *
 * COORDINATE SYSTEM (ingestion emission semantics, PR #80 / issue #87):
 * `start_char`/`end_char` are GLOBAL offsets into the canonical document text
 * of the parsed version, and `content` is exactly the canonical slice
 * `[start_char, end_char)`. SourceSpan offsets are ALSO global canonical
 * offsets — never section-local — so a span in any non-first section has
 * offsets that exceed its section's content length. Local render anchors are
 * derived at the last moment as `span.start_char - section.start_char` (see
 * spans.ts); persisted SourceSpan values are never mutated or rewritten.
 */
export interface SectionRecord {
  id: string;
  document_version_id: string;
  parent_id?: string;
  order: number;
  /** 1 = top-level part, 2 = item, 3 = statement/note. */
  level: number;
  title: string;
  /** Canonical global range this section covers (db sections.start_char). */
  start_char: number;
  /** Canonical global end offset, exclusive (db sections.end_char). */
  end_char: number;
  /** The exact canonical text slice `[start_char, end_char)`. */
  content: string;
}
