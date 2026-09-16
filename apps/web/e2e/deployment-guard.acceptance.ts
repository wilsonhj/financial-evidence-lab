import { createServer, type Server } from "node:http";
import { test, expect } from "@playwright/test";
let upstream: Server;
let calls = 0;
test.beforeAll(async () => {
  upstream = createServer((_request, response) => {
    calls++;
    response.writeHead(500).end();
  });
  await new Promise<void>((resolve, reject) => {
    upstream.once("error", reject);
    upstream.listen(8234, "127.0.0.1", resolve);
  });
});
test.afterAll(async () => {
  await new Promise<void>((resolve, reject) =>
    upstream.close((error) => (error ? reject(error) : resolve())),
  );
});
test("public production HTTP refuses business pages/actions/API/SSE without any upstream call", async ({
  request,
}) => {
  for (const path of [
    "/",
    "/desk",
    "/reader",
    "/reader/id",
    "/observatory",
    "/observatory/runs/id",
    "/extractions",
    "/extraction-runs/id",
    "/approved-extractions/id",
    "/api/extraction/permissions",
    "/api/extraction/runs/id/events",
    "/observatory/",
  ]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(503);
    expect(response.headers()["cache-control"]).toBe("no-store");
    if (path.startsWith("/api/"))
      expect((await response.json()).error.code).toBe("PUBLIC_AUTH_NOT_READY");
    else expect(await response.text()).toBe("Service unavailable");
  }
  for (const headers of [{ RSC: "1" }, { "Next-Router-Prefetch": "1", RSC: "1" }])
    expect((await request.get("/observatory", { headers })).status()).toBe(503);
  expect(
    (
      await request.post("/observatory", {
        headers: { "Next-Action": "untrusted-action" },
        data: "[]",
      })
    ).status(),
  ).toBe(503);
  expect((await request.post("/api/extraction/runs", { data: {} })).status()).toBe(503);
  expect((await request.delete("/api/extraction/runs/id")).status()).toBe(503);
  expect((await request.get("/api/health")).status()).toBe(200);
  expect(calls).toBe(0);
});
