import { describe, expect, it } from "vitest";

import type { SectionRecord, SourceSpanRecord } from "./contracts";
import {
  deriveLocalSpanAnchor,
  extractSpanText,
  resolveSegmentSelection,
  sectionRangeConsistent,
  segmentSection,
} from "./spans";

const DOC = "aaaaaaaa-0000-4000-8000-00000000ffff";
const SECTION = "bbbbbbbb-0000-4000-8000-00000000ffff";

const content = "Revenue was $10. Net income was $2.";

/**
 * A section positioned at a GLOBAL canonical offset. `base` defaults to 400
 * so — like every non-first section of a real filing — valid span offsets
 * exceed the section-content length (the #87 regression precondition). The
 * legacy `base = 0` first-section case is exercised explicitly below.
 */
function sectionAt(base: number, text = content, id = SECTION): SectionRecord {
  return {
    id,
    document_version_id: DOC,
    order: 1,
    level: 1,
    title: "Test",
    start_char: base,
    end_char: base + text.length,
    content: text,
  };
}

const BASE = 400;
const section = sectionAt(BASE);

/** Span with GLOBAL canonical offsets (section-local offset + section base). */
function spanRecord(id: string, start: number, end: number, sectionId = SECTION): SourceSpanRecord {
  return {
    id,
    span: {
      document_version_id: DOC,
      section_id: sectionId,
      start_char: start,
      end_char: end,
      text_hash: "sha256:" + "0".repeat(64),
    },
  };
}

/** Span addressed by SECTION-LOCAL offsets, converted to global coordinates. */
function localSpan(id: string, localStart: number, localEnd: number): SourceSpanRecord {
  return spanRecord(id, BASE + localStart, BASE + localEnd);
}

describe("segmentSection", () => {
  // THE #87 regression case: a valid span in a non-first section, whose
  // GLOBAL offsets exceed the section-content length (content is 35 chars;
  // the span starts at 400). The old section-local reading skipped it as
  // out-of-range; it must highlight the exact cited slice.
  it("maps global span offsets exceeding the section length onto exact local slices", () => {
    const span = localSpan("s1", 0, 16);
    expect(span.span.start_char).toBeGreaterThan(section.content.length);
    const segments = segmentSection(section, [span]);
    expect(segments).toEqual([
      { text: "Revenue was $10.", start: 0, end: 16, spanIds: ["s1"] },
      { text: " Net income was $2.", start: 16, end: content.length, spanIds: [] },
    ]);
  });

  // Backward path: a first section starting at global offset 0, where local
  // and global coordinates coincide.
  it("still handles a first section whose global range starts at 0", () => {
    const first = sectionAt(0);
    const segments = segmentSection(first, [spanRecord("s1", 17, 35)]);
    expect(segments).toEqual([
      { text: "Revenue was $10. ", start: 0, end: 17, spanIds: [] },
      { text: "Net income was $2.", start: 17, end: content.length, spanIds: ["s1"] },
    ]);
  });

  it("covers the entire content with no gaps and preserves the original text", () => {
    const segments = segmentSection(section, [localSpan("s1", 3, 8), localSpan("s2", 17, 35)]);
    expect(segments.map((segment) => segment.text).join("")).toBe(content);
    for (let i = 1; i < segments.length; i += 1) {
      expect(segments[i]!.start).toBe(segments[i - 1]!.end);
    }
  });

  it("splits overlapping spans at every boundary", () => {
    const segments = segmentSection(section, [localSpan("s1", 0, 16), localSpan("s2", 12, 20)]);
    expect(segments).toEqual([
      { text: "Revenue was ", start: 0, end: 12, spanIds: ["s1"] },
      { text: "$10.", start: 12, end: 16, spanIds: ["s1", "s2"] },
      { text: " Net", start: 16, end: 20, spanIds: ["s2"] },
      { text: " income was $2.", start: 20, end: content.length, spanIds: [] },
    ]);
  });

  it("ignores spans belonging to other sections", () => {
    const segments = segmentSection(section, [spanRecord("s1", BASE, BASE + 16, "other-section")]);
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  // Fail-closed containment: offsets outside the section's GLOBAL canonical
  // range are never clamped into plausible-looking highlights. This includes
  // the old world's section-LOCAL offsets (e.g. [0, 16) against a section
  // starting at 400).
  it("skips spans whose global offsets fall outside the section's canonical range", () => {
    const sectionLocalLeftover = spanRecord("s1", 0, 16); // pre-fix coordinates
    const pastEnd = spanRecord("s2", BASE + 30, BASE + 999);
    const beforeStart = spanRecord("s3", BASE - 5, BASE + 5);
    const segments = segmentSection(section, [sectionLocalLeftover, pastEnd, beforeStart]);
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  it("skips spans with reversed or empty offsets", () => {
    const segments = segmentSection(section, [localSpan("s1", 10, 4), localSpan("s2", 5, 5)]);
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  // Fail-closed equivalence: a section whose content is not exactly its
  // canonical slice length cannot anchor ANY span.
  it("skips every span of a section whose canonical range disagrees with its content", () => {
    const broken = { ...section, end_char: section.end_char + 3 };
    const segments = segmentSection(broken, [localSpan("s1", 0, 16)]);
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  it("handles empty content", () => {
    expect(segmentSection(sectionAt(BASE, ""), [localSpan("s1", 0, 5)])).toEqual([]);
  });
});

describe("deriveLocalSpanAnchor", () => {
  it("derives local anchors as span.start_char - section.start_char without mutating the span", () => {
    const span = localSpan("s1", 3, 8);
    const before = JSON.stringify(span);
    expect(deriveLocalSpanAnchor(section, span)).toEqual({ ok: true, start: 3, end: 8 });
    expect(JSON.stringify(span)).toBe(before);
  });

  it("fails closed with offsets_out_of_range for non-contained spans", () => {
    expect(deriveLocalSpanAnchor(section, spanRecord("s1", 0, 16))).toEqual({
      ok: false,
      reason: "offsets_out_of_range",
    });
    expect(deriveLocalSpanAnchor(section, spanRecord("s2", BASE, BASE + 999))).toEqual({
      ok: false,
      reason: "offsets_out_of_range",
    });
  });

  it("fails closed with section_range_mismatch for inconsistent sections", () => {
    const broken = { ...section, start_char: BASE + 1 };
    expect(deriveLocalSpanAnchor(broken, localSpan("s1", 3, 8))).toEqual({
      ok: false,
      reason: "section_range_mismatch",
    });
  });
});

describe("sectionRangeConsistent", () => {
  it("accepts a section whose content length equals end_char - start_char", () => {
    expect(sectionRangeConsistent(section)).toBe(true);
    expect(sectionRangeConsistent(sectionAt(0))).toBe(true);
    expect(sectionRangeConsistent(sectionAt(7, ""))).toBe(true);
  });

  it("rejects negative, non-integer, reversed, or length-mismatched ranges", () => {
    expect(sectionRangeConsistent({ ...section, start_char: -1 })).toBe(false);
    expect(sectionRangeConsistent({ ...section, start_char: 0.5 })).toBe(false);
    expect(sectionRangeConsistent({ ...section, end_char: section.start_char - 1 })).toBe(false);
    expect(sectionRangeConsistent({ ...section, end_char: section.end_char + 1 })).toBe(false);
  });
});

describe("extractSpanText", () => {
  it("returns the exact cited substring via the derived local anchor", () => {
    expect(extractSpanText(section, localSpan("s1", 17, 35))).toBe("Net income was $2.");
  });

  it("returns the exact cited substring for a base-0 first section", () => {
    expect(extractSpanText(sectionAt(0), spanRecord("s1", 17, 35))).toBe("Net income was $2.");
  });

  // Fail-closed: a span outside the section's canonical range must yield
  // null, never a clamped/empty string that quietly renders as a quote. A
  // section-LOCAL offset leftover is exactly such a span now.
  it("returns null for a span outside the section's canonical range", () => {
    expect(extractSpanText(section, spanRecord("s1", 0, 16))).toBeNull();
    expect(extractSpanText(section, spanRecord("s2", BASE + 100, BASE + 200))).toBeNull();
  });

  it("returns null for reversed offsets", () => {
    expect(extractSpanText(section, localSpan("s1", 10, 4))).toBeNull();
  });

  it("returns null when the section's canonical range disagrees with its content", () => {
    const broken = { ...section, end_char: section.end_char - 2 };
    expect(extractSpanText(broken, localSpan("s1", 3, 8))).toBeNull();
  });
});

describe("resolveSegmentSelection", () => {
  // outer covers [0, 30), inner covers [10, 14): the segment [10, 14) is
  // covered by both.
  const lengths = new Map([
    ["outer", 30],
    ["inner", 4],
  ]);

  // Regression (finding 6): clicking a multi-span segment used to select
  // spanIds[0] unconditionally, making nested spans unreachable.
  it("selects the narrowest covering span so nested spans are reachable", () => {
    expect(resolveSegmentSelection(["inner", "outer"], null, lengths)).toBe("inner");
    expect(resolveSegmentSelection(["outer", "inner"], null, lengths)).toBe("inner");
  });

  // Regression (finding 6): toggle-off used to work only when the selected
  // span happened to be spanIds[0].
  it("toggles off when the selected span covers the segment, whichever span it is", () => {
    expect(resolveSegmentSelection(["inner", "outer"], "outer", lengths)).toBeNull();
    expect(resolveSegmentSelection(["inner", "outer"], "inner", lengths)).toBeNull();
  });

  it("selects the narrowest span when a non-covering span is selected", () => {
    expect(resolveSegmentSelection(["inner", "outer"], "elsewhere", lengths)).toBe("inner");
  });

  it("breaks length ties deterministically by id", () => {
    const tied = new Map([
      ["b", 4],
      ["a", 4],
    ]);
    expect(resolveSegmentSelection(["b", "a"], null, tied)).toBe("a");
  });

  it("returns null for a segment with no spans", () => {
    expect(resolveSegmentSelection([], null, lengths)).toBeNull();
  });

  it("falls back to the first span when lengths are unknown", () => {
    expect(resolveSegmentSelection(["x", "y"], null, new Map())).toBe("x");
  });
});
