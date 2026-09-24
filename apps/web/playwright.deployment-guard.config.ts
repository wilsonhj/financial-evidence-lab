import { defineConfig } from "@playwright/test";
const PORT = 3234;
const id = "11111111-1111-4111-8111-111111111111";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "deployment-guard.acceptance.ts",
  workers: 1,
  retries: 0,
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  webServer: {
    command: `pnpm exec next build && pnpm exec next start --hostname 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    env: {
      FEL_DEPLOYMENT_MODE: "public",
      FEL_EVIDENCE_SOURCE: "http",
      FEL_AUTH_MODE: "mock",
      FEL_READER_SMOKE_TARGET: "guard-proof",
      FEL_API_BASE_URL: "http://127.0.0.1:8234",
      FEL_API_BEARER_TOKEN: `mock.${Buffer.from(JSON.stringify({ org_id: id, sub: id, role: "owner" })).toString("base64url")}`,
      FEL_ENTITY_IDS: id,
      FEL_WORKSPACE_ID: id,
    },
  },
});
