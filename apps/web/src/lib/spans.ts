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

/** Clamp a span to the section bounds; returns null when nothing overlaps. */
function clampToSection(
  start: number,
  end: number,
  length: number,
): { start: number; end: number } | null {
  const s = Math.max(0, Math.min(start, length));
  const e = Math.max(0, Math.min(end, length));
  if (e <= s) return null;
  return { start: s, end: e };
}

/**
 * Maps section-relative span offsets onto the section text, producing an
 * ordered, gap-free list of segments covering the whole content. Handles
 * overlapping and adjacent spans and clamps out-of-range offsets rather than
 * throwing, so a bad span can never corrupt document rendering.
 */
export function segmentSection(
  content: string,
  spans: readonly SourceSpanRecord[],
  sectionId: string,
): SectionSegment[] {
  const relevant: { id: string; start: number; end: number }[] = [];
  for (const record of spans) {
    if (record.span.section_id !== sectionId) continue;
    const clamped = clampToSection(record.span.start_char, record.span.end_char, content.length);
    if (clamped) relevant.push({ id: record.id, ...clamped });
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

/** Extracts the exact raw source text a span cites from its section content. */
export function extractSpanText(section: SectionRecord, record: SourceSpanRecord): string {
  const clamped = clampToSection(
    record.span.start_char,
    record.span.end_char,
    section.content.length,
  );
  if (!clamped) return "";
  return section.content.slice(clamped.start, clamped.end);
}
