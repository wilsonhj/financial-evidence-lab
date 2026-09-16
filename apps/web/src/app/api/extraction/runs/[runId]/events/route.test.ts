import { afterEach, expect, it, vi } from "vitest";
import { GET } from "./route";
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
it("refuses direct SSE invocation before fetching with a generic public error", async () => {
  vi.stubEnv("FEL_DEPLOYMENT_MODE", "public")
    .stubEnv("FEL_EVIDENCE_SOURCE", "http")
    .stubEnv("FEL_API_BEARER_TOKEN", "sensitive");
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const response = await GET(new Request("http://web.test/api/extraction/runs/id/events"), {
    params: Promise.resolve({ runId: "id" }),
  });
  expect(response.status).toBe(503);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect((await response.json()).error.code).toBe("PUBLIC_AUTH_NOT_READY");
  expect(fetcher).not.toHaveBeenCalled();
});
