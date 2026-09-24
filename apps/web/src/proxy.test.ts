import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { proxy, config } from "./proxy";
afterEach(() => vi.unstubAllEnvs());
it.each([undefined, "public", "", "typo", "reader-smoke", "synthetic-http"])(
  "returns safe uncached refusal in mode %s",
  async (mode) => {
    vi.stubEnv("FEL_DEPLOYMENT_MODE", mode);
    for (const path of ["/reader/id", "/api/extraction/permissions"]) {
      const response = proxy(new NextRequest(`http://web.test${path}`));
      expect(response.status).toBe(503);
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(await response.text()).not.toContain("Bearer");
    }
  },
);
it("allows explicitly offline fixtures and excludes health/static matchers", () => {
  vi.stubEnv("FEL_DEPLOYMENT_MODE", "fixture")
    .stubEnv("FEL_EVIDENCE_SOURCE", "fixture")
    .stubEnv("FEL_API_BEARER_TOKEN", "");
  expect(proxy(new NextRequest("http://web.test/reader")).headers.get("x-middleware-next")).toBe(
    "1",
  );
  expect(config.matcher).not.toContain("/api/health");
  expect(config.matcher).not.toContain("/_next/:path*");
});
