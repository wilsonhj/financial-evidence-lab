import type { SectionRecord, SourceSpanRecord } from "./contracts";

/**
 * A contiguous slice of a section's content. `spanIds` lists every source
 * span covering the slice (empty = plain text). Overlapping spans are split
 * at every span boundary so each segment has a stable set of covering spans.
 */
export interface SectionSegment {
  text: string;
  start: number;
  end: number;
  spanIds: string[];
}

/** Offsets are valid only when 0 <= start < end <= length (fail-closed). */
function offsetsValid(start: number, end: number, length: number): boolean {
  return (
    Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start && end <= length
  );
}

/**
 * Maps section-relative span offsets onto the section text, producing an
 * ordered, gap-free list of segments covering the whole content. Handles
 * overlapping and adjacent spans.
 *
 * Fail-closed: spans with out-of-range or empty offsets are SKIPPED, never
 * clamped into plausible-looking highlights. Callers are expected to have
 * already excluded and flagged invalid spans via
 * `verifySpanIntegrity` (see citation-integrity.ts); the skip here is a
 * defensive second line, not an error channel.
 */
export function segmentSection(
  content: string,
  spans: readonly SourceSpanRecord[],
  sectionId: string,
): SectionSegment[] {
  const relevant: { id: string; start: number; end: number }[] = [];
  for (const record of spans) {
    if (record.span.section_id !== sectionId) continue;
    const { start_char: start, end_char: end } = record.span;
    if (!offsetsValid(start, end, content.length)) continue;
    relevant.push({ id: record.id, start, end });
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
 * Extracts the exact raw source text a span cites from its section content,
 * or null when the offsets are invalid for that content. Callers must treat
 * null as "citation cannot be trusted" — there is no clamped best-effort
 * substring.
 */
export function extractSpanText(section: SectionRecord, record: SourceSpanRecord): string | null {
  const { start_char: start, end_char: end } = record.span;
  if (!offsetsValid(start, end, section.content.length)) return null;
  return section.content.slice(start, end);
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
