import { describe, expect, it } from "vitest";

import { formatPeriodRange } from "./document-display";

describe("formatPeriodRange", () => {
  it("renders a full period range", () => {
    expect(formatPeriodRange({ period_start: "2026-01-01", period_end: "2026-03-31" })).toBe(
      "2026-01-01 to 2026-03-31",
    );
  });

  // Regression (finding 7): absent period fields used to render as the
  // literal text "undefined to undefined".
  it("renders an explicit n/a fallback when both period fields are absent", () => {
    expect(formatPeriodRange({})).toBe("n/a");
    expect(formatPeriodRange({ period_start: undefined, period_end: undefined })).toBe("n/a");
  });

  it("renders partial periods with n/a for the missing side", () => {
    expect(formatPeriodRange({ period_start: "2026-01-01" })).toBe("2026-01-01 to n/a");
    expect(formatPeriodRange({ period_end: "2026-03-31" })).toBe("n/a to 2026-03-31");
  });

  it("never emits the string 'undefined'", () => {
    for (const doc of [{}, { period_start: "2026-01-01" }, { period_end: "2026-03-31" }]) {
      expect(formatPeriodRange(doc)).not.toContain("undefined");
    }
  });
});
