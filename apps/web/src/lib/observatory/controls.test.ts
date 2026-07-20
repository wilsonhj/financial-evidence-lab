import { describe, expect, it } from "vitest";

import { validateControls } from "./controls";

const base = { question: "What was revenue?", lanes: ["dense", "lexical"] };

describe("validateControls", () => {
  it("accepts in-bounds controls and builds a CreateQuery, omitting empty fields", () => {
    const { errors, query } = validateControls({ ...base, topK: "25", forms: "10-Q, 10-K" });
    expect(errors).toEqual([]);
    expect(query).toEqual({
      question: "What was revenue?",
      lanes: ["dense", "lexical"],
      top_k: 25,
      forms: ["10-Q", "10-K"],
    });
  });

  it("rejects a top_k outside 1..100", () => {
    expect(validateControls({ ...base, topK: "0" }).query).toBeUndefined();
    expect(validateControls({ ...base, topK: "101" }).query).toBeUndefined();
    expect(validateControls({ ...base, topK: "10.5" }).query).toBeUndefined();
    expect(validateControls({ ...base, topK: "25" }).query).toBeDefined();
  });

  it("rejects an unknown lane and requires a question", () => {
    expect(validateControls({ ...base, lanes: ["dense", "bogus"] }).errors).toContain(
      "Unknown retrieval lane selected.",
    );
    expect(validateControls({ ...base, question: "  " }).errors).toContain("Question is required.");
  });

  it("rejects more than 20 form or period filters", () => {
    const many = Array.from({ length: 21 }, (_, index) => `f${index}`).join(",");
    expect(validateControls({ ...base, forms: many }).query).toBeUndefined();
    expect(validateControls({ ...base, periods: many }).query).toBeUndefined();
  });

  it("normalises an offset-less datetime-local cutoff to an aware UTC datetime", () => {
    expect(validateControls({ ...base, asOf: "not-a-date" }).query).toBeUndefined();
    // A <input type="datetime-local"> emits an OFFSET-LESS value; it must be
    // forwarded as an aware RFC3339 datetime (UTC) or the API rejects it 422.
    const local = validateControls({ ...base, asOf: "2026-06-30T23:59" });
    expect(local.query?.as_of).toBe("2026-06-30T23:59:00Z");
    expect(local.query?.as_of).toMatch(/Z$/);
    // An already-aware value is preserved.
    const aware = validateControls({ ...base, asOf: "2026-06-30T23:59:59Z" });
    expect(aware.query?.as_of).toBe("2026-06-30T23:59:59Z");
  });

  it("omits lanes entirely when none are selected (server default applies)", () => {
    const { query } = validateControls({ ...base, lanes: [] });
    expect(query && "lanes" in query).toBe(false);
  });
});
