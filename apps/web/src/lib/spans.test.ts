import { describe, expect, it } from "vitest";

import type { SectionRecord, SourceSpanRecord } from "./contracts";
import { extractSpanText, resolveSegmentSelection, segmentSection } from "./spans";

const DOC = "aaaaaaaa-0000-4000-8000-00000000ffff";
const SECTION = "bbbbbbbb-0000-4000-8000-00000000ffff";

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

const content = "Revenue was $10. Net income was $2.";

describe("segmentSection", () => {
  it("maps span offsets onto exact text slices", () => {
    const segments = segmentSection(content, [spanRecord("s1", 0, 16)], SECTION);
    expect(segments).toEqual([
      { text: "Revenue was $10.", start: 0, end: 16, spanIds: ["s1"] },
      { text: " Net income was $2.", start: 16, end: content.length, spanIds: [] },
    ]);
  });

  it("covers the entire content with no gaps and preserves the original text", () => {
    const segments = segmentSection(
      content,
      [spanRecord("s1", 3, 8), spanRecord("s2", 17, 35)],
      SECTION,
    );
    expect(segments.map((segment) => segment.text).join("")).toBe(content);
    for (let i = 1; i < segments.length; i += 1) {
      expect(segments[i]!.start).toBe(segments[i - 1]!.end);
    }
  });

  it("splits overlapping spans at every boundary", () => {
    const segments = segmentSection(
      content,
      [spanRecord("s1", 0, 16), spanRecord("s2", 12, 20)],
      SECTION,
    );
    expect(segments).toEqual([
      { text: "Revenue was ", start: 0, end: 12, spanIds: ["s1"] },
      { text: "$10.", start: 12, end: 16, spanIds: ["s1", "s2"] },
      { text: " Net", start: 16, end: 20, spanIds: ["s2"] },
      { text: " income was $2.", start: 20, end: content.length, spanIds: [] },
    ]);
  });

  it("ignores spans belonging to other sections", () => {
    const segments = segmentSection(content, [spanRecord("s1", 0, 16, "other-section")], SECTION);
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  // Regression (finding 2, fail-open citations): out-of-range offsets used to
  // be silently CLAMPED into a plausible-looking highlight. They must now be
  // skipped entirely — flagging is the verification layer's job.
  it("skips spans with out-of-range offsets instead of clamping them", () => {
    const segments = segmentSection(content, [spanRecord("s1", 30, 999)], SECTION);
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  it("skips spans with negative or reversed offsets", () => {
    const segments = segmentSection(
      content,
      [spanRecord("s1", -2, 5), spanRecord("s2", 10, 4)],
      SECTION,
    );
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  it("drops empty and fully out-of-range spans", () => {
    const segments = segmentSection(
      content,
      [spanRecord("s1", 5, 5), spanRecord("s2", 400, 500)],
      SECTION,
    );
    expect(segments).toEqual([{ text: content, start: 0, end: content.length, spanIds: [] }]);
  });

  it("handles empty content", () => {
    expect(segmentSection("", [spanRecord("s1", 0, 5)], SECTION)).toEqual([]);
  });
});

describe("extractSpanText", () => {
  const section: SectionRecord = {
    id: SECTION,
    document_version_id: DOC,
    order: 1,
    level: 1,
    title: "Test",
    content,
  };

  it("returns the exact cited substring", () => {
    expect(extractSpanText(section, spanRecord("s1", 17, 35))).toBe("Net income was $2.");
  });

  // Regression (finding 2): a span outside the content used to yield a
  // clamped/empty string that quietly rendered as a quote; it must now be
  // null so callers cannot treat it as verified text.
  it("returns null for a span outside the content", () => {
    expect(extractSpanText(section, spanRecord("s1", 100, 200))).toBeNull();
  });

  it("returns null for reversed offsets", () => {
    expect(extractSpanText(section, spanRecord("s1", 10, 4))).toBeNull();
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
