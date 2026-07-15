import type { SectionRecord, SourceSpanRecord } from "./contracts";

/**
 * A contiguous slice of a section's content. `spanIds` lists every source
 * span covering the slice (empty = plain text). Overlapping spans are split
 * at every span boundary so each segment has a stable set of covering spans.
 *
 * `start`/`end` are SECTION-LOCAL render anchors (offsets into `content`),
 * derived from the global canonical coordinates at the last moment — they are
 * a view-model detail and are never written back onto any SourceSpan.
 */
export interface SectionSegment {
  text: string;
  start: number;
  end: number;
  spanIds: string[];
}

/**
 * True when a section's global canonical range is internally consistent:
 * integer bounds, 0 <= start <= end, and `content` is exactly the canonical
 * slice length `end_char - start_char`. A section failing this check cannot
 * anchor any span (fail-closed).
 */
export function sectionRangeConsistent(section: SectionRecord): boolean {
  return (
    Number.isInteger(section.start_char) &&
    Number.isInteger(section.end_char) &&
    section.start_char >= 0 &&
    section.end_char >= section.start_char &&
    section.content.length === section.end_char - section.start_char
  );
}

/**
 * Result of deriving a section-local anchor from a span's GLOBAL canonical
 * offsets. Failures name which invariant broke so the verification layer
 * (citation-integrity.ts) can surface the precise reason; rendering code
 * treats any failure as "do not highlight".
 */
export type LocalAnchorResult =
  | { ok: true; start: number; end: number }
  | { ok: false; reason: "section_range_mismatch" | "offsets_out_of_range" };

/**
 * Derives the section-local render anchor for a span:
 * `local = span.start_char - section.start_char`.
 *
 * Fail-closed, never clamped:
 * - the section's own canonical range must be consistent
 *   (`section_range_mismatch` otherwise);
 * - the span's global offsets must be integers, non-empty, and fully
 *   CONTAINED in the section's global range
 *   (`offsets_out_of_range` otherwise).
 *
 * The input SourceSpan is read, never mutated: global offsets remain the only
 * persisted coordinates.
 */
export function deriveLocalSpanAnchor(
  section: SectionRecord,
  record: SourceSpanRecord,
): LocalAnchorResult {
  if (!sectionRangeConsistent(section)) {
    return { ok: false, reason: "section_range_mismatch" };
  }
  const { start_char: start, end_char: end } = record.span;
  const contained =
    Number.isInteger(start) &&
    Number.isInteger(end) &&
    start >= section.start_char &&
    end > start &&
    end <= section.end_char;
  if (!contained) return { ok: false, reason: "offsets_out_of_range" };
  return { ok: true, start: start - section.start_char, end: end - section.start_char };
}

/**
 * Maps spans onto the section text, producing an ordered, gap-free list of
 * segments covering the whole content. Span offsets are GLOBAL canonical
 * offsets; local anchors are derived per span via `deriveLocalSpanAnchor`.
 * Handles overlapping and adjacent spans.
 *
 * Fail-closed: spans whose global offsets fall outside the section's
 * canonical range (and all spans of a section whose own range is
 * inconsistent) are SKIPPED, never clamped into plausible-looking highlights.
 * Callers are expected to have already excluded and flagged invalid spans via
 * `verifySpanIntegrity` (see citation-integrity.ts); the skip here is a
 * defensive second line, not an error channel.
 */
export function segmentSection(
  section: SectionRecord,
  spans: readonly SourceSpanRecord[],
): SectionSegment[] {
  const content = section.content;
  const relevant: { id: string; start: number; end: number }[] = [];
  for (const record of spans) {
    if (record.span.section_id !== section.id) continue;
    const anchor = deriveLocalSpanAnchor(section, record);
    if (!anchor.ok) continue;
    relevant.push({ id: record.id, start: anchor.start, end: anchor.end });
  }

  const boundaries = new Set<number>([0, content.length]);
  for (const span of relevant) {
    boundaries.add(span.start);
    boundaries.add(span.end);
  }
  const cuts = [...boundaries].sort((a, b) => a - b);

  const segments: SectionSegment[] = [];
  for (let i = 0; i < cuts.length - 1; i += 1) {
    const start = cuts[i]!;
    const end = cuts[i + 1]!;
    const spanIds = relevant
      .filter((span) => span.start <= start && span.end >= end)
      .map((span) => span.id)
      .sort();
    segments.push({ text: content.slice(start, end), start, end, spanIds });
  }
  return segments;
}

/**
 * Extracts the exact raw source text a span cites from its section content
 * (sliced via the derived local anchor), or null when the span's global
 * offsets are invalid for that section. Callers must treat null as "citation
 * cannot be trusted" — there is no clamped best-effort substring.
 */
export function extractSpanText(section: SectionRecord, record: SourceSpanRecord): string | null {
  const anchor = deriveLocalSpanAnchor(section, record);
  if (!anchor.ok) return null;
  return section.content.slice(anchor.start, anchor.end);
}

/**
 * Resolves a click (or keyboard activation) on a multi-span segment:
 *
 * - if the currently selected span covers this segment, the click DESELECTS
 *   it (toggle-off) regardless of which covering span is selected;
 * - otherwise the NARROWEST covering span (minimum end-start; id as the
 *   deterministic tie-break) is selected, so nested spans stay reachable.
 */
export function resolveSegmentSelection(
  segmentSpanIds: readonly string[],
  selectedSpanId: string | null,
  spanLengthById: ReadonlyMap<string, number>,
): string | null {
  if (selectedSpanId !== null && segmentSpanIds.includes(selectedSpanId)) return null;
  let best: string | null = null;
  let bestLength = Infinity;
  for (const id of segmentSpanIds) {
    const length = spanLengthById.get(id) ?? Infinity;
    if (length < bestLength || (length === bestLength && best !== null && id < best)) {
      best = id;
      bestLength = length;
    }
  }
  return best ?? segmentSpanIds[0] ?? null;
}
