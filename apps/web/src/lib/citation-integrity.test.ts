import { describe, expect, it } from "vitest";

import type { SectionRecord, SourceSpanRecord } from "./contracts";
import { sha256Hex, verifySpanIntegrity } from "./citation-integrity";

const DOC_VERSION = "aaaaaaaa-0000-4000-8000-00000000ffff";
const SECTION = "bbbbbbbb-0000-4000-8000-00000000ffff";

const content = "Revenue was $10. Net income was $2.";

const section: SectionRecord = {
  id: SECTION,
  document_version_id: DOC_VERSION,
  order: 1,
  level: 1,
  title: "Test",
  content,
};

function spanRecord(
  id: string,
  start: number,
  end: number,
  overrides: Partial<{ text_hash: string; section_id: string }> = {},
): SourceSpanRecord {
  return {
    id,
    span: {
      document_version_id: DOC_VERSION,
      section_id: overrides.section_id ?? SECTION,
      start_char: start,
      end_char: end,
      text_hash: overrides.text_hash ?? `sha256:${sha256Hex(content.slice(start, end))}`,
    },
  };
}

describe("verifySpanIntegrity", () => {
  it("verifies spans whose offsets are in range and whose hash matches", () => {
    const good = spanRecord("s1", 0, 16);
    const result = verifySpanIntegrity([section], [good]);
    expect(result.verified).toEqual([good]);
    expect(result.failures).toEqual([]);
  });

  // Regression (finding 2): out-of-range offsets used to be silently clamped
  // into a plausible quote; they must fail closed instead.
  it("fails spans with out-of-range offsets", () => {
    const result = verifySpanIntegrity([section], [spanRecord("s1", 30, 999)]);
    expect(result.verified).toEqual([]);
    expect(result.failures).toEqual([
      { spanId: "s1", sectionId: SECTION, reason: "offsets_out_of_range" },
    ]);
  });

  it("fails spans with reversed, empty, or negative offsets", () => {
    const result = verifySpanIntegrity(
      [section],
      [spanRecord("r", 10, 4), spanRecord("e", 5, 5), spanRecord("n", -1, 4)],
    );
    expect(result.verified).toEqual([]);
    expect(result.failures.map((failure) => failure.reason)).toEqual([
      "offsets_out_of_range",
      "offsets_out_of_range",
      "offsets_out_of_range",
    ]);
  });

  // Regression (finding 2): text_hash was only ever checked in fixture tests,
  // never at data-load time, so a tampered/drifted citation rendered as a
  // verified quote.
  it("fails spans whose text_hash does not match the exact cited slice", () => {
    const tampered = spanRecord("s1", 0, 16, {
      text_hash: `sha256:${sha256Hex("Revenue was $99.")}`,
    });
    const result = verifySpanIntegrity([section], [tampered]);
    expect(result.verified).toEqual([]);
    expect(result.failures).toEqual([
      { spanId: "s1", sectionId: SECTION, reason: "text_hash_mismatch" },
    ]);
  });

  it("fails spans anchored to an unknown section", () => {
    const orphan = spanRecord("s1", 0, 16, { section_id: "cccccccc-0000-4000-8000-000000000bad" });
    const result = verifySpanIntegrity([section], [orphan]);
    expect(result.verified).toEqual([]);
    expect(result.failures).toEqual([
      {
        spanId: "s1",
        sectionId: "cccccccc-0000-4000-8000-000000000bad",
        reason: "unknown_section",
      },
    ]);
  });

  it("keeps good spans while excluding bad ones", () => {
    const good = spanRecord("good", 17, 35);
    const bad = spanRecord("bad", 0, 999);
    const result = verifySpanIntegrity([section], [good, bad]);
    expect(result.verified).toEqual([good]);
    expect(result.failures.map((failure) => failure.spanId)).toEqual(["bad"]);
  });
});
