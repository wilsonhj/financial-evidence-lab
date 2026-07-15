import { describe, expect, it } from "vitest";

import type { SectionRecord, SourceSpanRecord } from "./contracts";
import { sha256Hex, verifySpanIntegrity } from "./citation-integrity";

const DOC_VERSION = "aaaaaaaa-0000-4000-8000-00000000ffff";
const SECTION = "bbbbbbbb-0000-4000-8000-00000000ffff";

const content = "Revenue was $10. Net income was $2.";

/**
 * The section sits at a nonzero GLOBAL canonical offset (like every
 * non-first section of a real filing), so valid span offsets EXCEED the
 * section-content length — the #87 regression precondition.
 */
const BASE = 400;

const section: SectionRecord = {
  id: SECTION,
  document_version_id: DOC_VERSION,
  order: 1,
  level: 1,
  title: "Test",
  start_char: BASE,
  end_char: BASE + content.length,
  content,
};

/** Span addressed by SECTION-LOCAL offsets, stored with GLOBAL coordinates. */
function spanRecord(
  id: string,
  localStart: number,
  localEnd: number,
  overrides: Partial<{ text_hash: string; section_id: string }> = {},
): SourceSpanRecord {
  return {
    id,
    span: {
      document_version_id: DOC_VERSION,
      section_id: overrides.section_id ?? SECTION,
      start_char: BASE + localStart,
      end_char: BASE + localEnd,
      text_hash: overrides.text_hash ?? `sha256:${sha256Hex(content.slice(localStart, localEnd))}`,
    },
  };
}

describe("verifySpanIntegrity", () => {
  // THE #87 regression case: a valid non-first-section span whose global
  // offsets exceed the section-content length must VERIFY (the old
  // section-local reading failed it as out-of-range).
  it("verifies spans whose global offsets are contained and whose hash matches the derived-local slice", () => {
    const good = spanRecord("s1", 0, 16);
    expect(good.span.start_char).toBeGreaterThan(section.content.length);
    const result = verifySpanIntegrity([section], [good]);
    expect(result.verified).toEqual([good]);
    expect(result.failures).toEqual([]);
  });

  it("verifies spans in a first section whose global range starts at 0 (backward path)", () => {
    const first: SectionRecord = { ...section, start_char: 0, end_char: content.length };
    const good: SourceSpanRecord = {
      id: "s1",
      span: {
        document_version_id: DOC_VERSION,
        section_id: SECTION,
        start_char: 17,
        end_char: 35,
        text_hash: `sha256:${sha256Hex(content.slice(17, 35))}`,
      },
    };
    const result = verifySpanIntegrity([first], [good]);
    expect(result.verified).toEqual([good]);
    expect(result.failures).toEqual([]);
  });

  // Containment fails closed, never clamps. A section-LOCAL leftover offset
  // (e.g. [0, 16) against a section starting at 400) is exactly such a span.
  it("fails spans whose global offsets fall outside the section's canonical range", () => {
    const sectionLocalLeftover: SourceSpanRecord = {
      id: "s1",
      span: {
        document_version_id: DOC_VERSION,
        section_id: SECTION,
        start_char: 0,
        end_char: 16,
        text_hash: `sha256:${sha256Hex(content.slice(0, 16))}`,
      },
    };
    const pastEnd = spanRecord("s2", 30, 999);
    const result = verifySpanIntegrity([section], [sectionLocalLeftover, pastEnd]);
    expect(result.verified).toEqual([]);
    expect(result.failures).toEqual([
      { spanId: "s1", sectionId: SECTION, reason: "offsets_out_of_range" },
      { spanId: "s2", sectionId: SECTION, reason: "offsets_out_of_range" },
    ]);
  });

  it("fails spans with reversed, empty, or before-section offsets", () => {
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

  // Equivalence check: a section whose content is not exactly the canonical
  // slice `[start_char, end_char)` cannot anchor any span.
  it("fails every span of a section whose canonical range disagrees with its content length", () => {
    const broken: SectionRecord = { ...section, end_char: section.end_char + 5 };
    const result = verifySpanIntegrity([broken], [spanRecord("s1", 0, 16)]);
    expect(result.verified).toEqual([]);
    expect(result.failures).toEqual([
      { spanId: "s1", sectionId: SECTION, reason: "section_range_mismatch" },
    ]);
  });

  // Regression (finding 2): text_hash was only ever checked in fixture tests,
  // never at data-load time, so a tampered/drifted citation rendered as a
  // verified quote. The hash is checked against the DERIVED-local slice.
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
