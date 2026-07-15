import { createHash } from "node:crypto";

import type { SectionRecord, SourceSpanRecord } from "./contracts";
import { deriveLocalSpanAnchor } from "./spans";

/**
 * Fail-closed citation verification (server side, data-load time).
 *
 * Span offsets are GLOBAL canonical-document offsets (ingestion emission
 * semantics, PR #80 / issue #87). A span may only be rendered as a
 * highlighted citation or quoted as verified source text after ALL checks
 * pass against the section it anchors to:
 *
 *  1. the section's own canonical range is consistent — integer bounds,
 *     0 <= start_char <= end_char, and `content.length` equals
 *     `end_char - start_char`;
 *  2. the span's global offsets are integers, non-empty, and fully contained
 *     in the section's global range
 *     (section.start_char <= start < end <= section.end_char);
 *  3. sha256 of the exact section-content slice at the DERIVED local anchor
 *     (`span.start_char - section.start_char`) matches the span's
 *     `text_hash`.
 *
 * A failing span is EXCLUDED from highlighting and quoting and surfaced as an
 * explicit citation-integrity error — never silently clamped into a
 * plausible-looking quote. SourceSpan values are never mutated.
 */

export type CitationIntegrityReason =
  "unknown_section" | "section_range_mismatch" | "offsets_out_of_range" | "text_hash_mismatch";

export interface CitationIntegrityFailure {
  spanId: string;
  sectionId: string;
  reason: CitationIntegrityReason;
}

export interface SpanVerificationResult {
  /** Spans whose offsets and text_hash verified against their section. */
  verified: SourceSpanRecord[];
  /** Spans excluded from rendering, with the failed check named. */
  failures: CitationIntegrityFailure[];
}

export function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** Verifies every span against its section; see module doc for the checks. */
export function verifySpanIntegrity(
  sections: readonly SectionRecord[],
  spans: readonly SourceSpanRecord[],
): SpanVerificationResult {
  const sectionsById = new Map(sections.map((section) => [section.id, section]));
  const verified: SourceSpanRecord[] = [];
  const failures: CitationIntegrityFailure[] = [];

  for (const record of spans) {
    const { section_id: sectionId, text_hash: hash } = record.span;
    const section = sectionsById.get(sectionId);
    if (!section) {
      failures.push({ spanId: record.id, sectionId, reason: "unknown_section" });
      continue;
    }
    const anchor = deriveLocalSpanAnchor(section, record);
    if (!anchor.ok) {
      failures.push({ spanId: record.id, sectionId, reason: anchor.reason });
      continue;
    }
    const cited = section.content.slice(anchor.start, anchor.end);
    if (`sha256:${sha256Hex(cited)}` !== hash) {
      failures.push({ spanId: record.id, sectionId, reason: "text_hash_mismatch" });
      continue;
    }
    verified.push(record);
  }

  return { verified, failures };
}

/** Human-readable description of a failed integrity check. */
export function describeIntegrityReason(reason: CitationIntegrityReason): string {
  switch (reason) {
    case "unknown_section":
      return "the cited section is unknown";
    case "section_range_mismatch":
      return "the cited section's canonical range does not match its content";
    case "offsets_out_of_range":
      return "the cited character offsets fall outside the section's canonical range";
    case "text_hash_mismatch":
      return "the cited text does not match its recorded hash";
  }
}
