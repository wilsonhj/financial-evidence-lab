import { describe, expect, it } from "vitest";

import { KNOWN_OBSERVATORY_ERRORS, sanitizeObservatoryError } from "./known-errors";

describe("sanitizeObservatoryError", () => {
  it("passes through allowlisted action-failure slugs", () => {
    for (const slug of KNOWN_OBSERVATORY_ERRORS) {
      expect(sanitizeObservatoryError(slug)).toBe(slug);
    }
  });

  it("drops unknown or injected query strings", () => {
    expect(sanitizeObservatoryError("<script>alert(1)</script>")).toBeUndefined();
    expect(sanitizeObservatoryError("not_a_real_error")).toBeUndefined();
    expect(sanitizeObservatoryError("Top-k must be an integer between 1 and 100.")).toBeUndefined();
    expect(sanitizeObservatoryError(undefined)).toBeUndefined();
    expect(sanitizeObservatoryError("")).toBeUndefined();
  });
});
