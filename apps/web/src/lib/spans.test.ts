import { describe, expect, it } from "vitest";

import type { SectionRecord, SourceSpanRecord } from "./contracts";
import { extractSpanText, segmentSection } from "./spans";

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

  it("clamps out-of-range offsets instead of throwing", () => {
    const segments = segmentSection(content, [spanRecord("s1", 30, 999)], SECTION);
    expect(segments).toEqual([
      { text: content.slice(0, 30), start: 0, end: 30, spanIds: [] },
      { text: content.slice(30), start: 30, end: content.length, spanIds: ["s1"] },
    ]);
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

  it("returns empty text for a span outside the content", () => {
    expect(extractSpanText(section, spanRecord("s1", 100, 200))).toBe("");
  });
});
