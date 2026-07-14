import { createHash } from "node:crypto";

import type { SectionRecord, SourceSpanRecord } from "./contracts";

/**
 * Fail-closed citation verification (server side, data-load time).
 *
 * A span may only be rendered as a highlighted citation or quoted as verified
 * source text after BOTH checks pass against the section content it anchors
 * to:
 *
 *  1. offsets are integers, in-range, and non-empty (0 <= start < end <= len);
 *  2. sha256 of the exact `content.slice(start_char, end_char)` matches the
 *     span's `text_hash`.
 *
 * A failing span is EXCLUDED from highlighting and quoting and surfaced as an
 * explicit citation-integrity error — never silently clamped into a
 * plausible-looking quote.
 */

export type CitationIntegrityReason =
  "unknown_section" | "offsets_out_of_range" | "text_hash_mismatch";

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

function offsetsInRange(start: number, end: number, length: number): boolean {
  return (
    Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= length
  );
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
    const {
      section_id: sectionId,
      start_char: start,
      end_char: end,
      text_hash: hash,
    } = record.span;
    const section = sectionsById.get(sectionId);
    if (!section) {
      failures.push({ spanId: record.id, sectionId, reason: "unknown_section" });
      continue;
    }
    if (!offsetsInRange(start, end, section.content.length)) {
      failures.push({ spanId: record.id, sectionId, reason: "offsets_out_of_range" });
      continue;
    }
    const cited = section.content.slice(start, end);
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
    case "offsets_out_of_range":
      return "the cited character offsets fall outside the section text";
    case "text_hash_mismatch":
      return "the cited text does not match its recorded hash";
  }
}
