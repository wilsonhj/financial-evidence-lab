import { describe, expect, it } from "vitest";

import { health } from "./health";

describe("health", () => {
  it("reports ok for a named service", () => {
    expect(health("fel-web")).toEqual({ status: "ok", service: "fel-web", version: "0.0.0" });
  });

  it("carries an explicit version", () => {
    expect(health("fel-web", "1.2.3").version).toBe("1.2.3");
  });
});
