import { describe, expect, it } from "vitest";

import { health } from "./health";

describe("health", () => {
  it("reports ok for a named service", () => {
    expect(health("fel-web")).toEqual({ status: "ok", service: "fel-web" });
  });
});
