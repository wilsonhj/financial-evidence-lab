import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const manifestPath = process.env.CROSS_STACK_MANIFEST;
if (!manifestPath) throw new Error("CROSS_STACK_MANIFEST must name the seeded acceptance manifest");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, string>;
const root = fileURLToPath(new URL("../..", import.meta.url));
const python = process.env.FEL_ACCEPTANCE_PYTHON ?? "python";
const api = "http://127.0.0.1:8211";
const web = "http://127.0.0.1:3211";
const token = `mock.${Buffer.from(
  JSON.stringify({ org_id: manifest.org, sub: manifest.user, role: "owner" }),
).toString("base64url")}`;
const env = {
  FEL_DEPLOYMENT_MODE: "synthetic-http",
  FEL_SYNTHETIC_HTTP_TARGET: manifest.target!,
  CROSS_STACK_MANIFEST: manifestPath,
  FEL_AUTH_MODE: "mock",
  FEL_ALLOW_MOCK_LLM: "1",
  FEL_EVIDENCE_SOURCE: "http",
  FEL_API_BASE_URL: api,
  FEL_API_BEARER_TOKEN: token,
  FEL_WORKSPACE_ID: manifest.workspace!,
  FEL_ENTITY_IDS: manifest.entity!,
  FEL_RATE_LIMIT_BURST: "200",
};

export default defineConfig({
  testDir: "./e2e",
  testMatch: "extraction-cross-stack.acceptance.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  use: { baseURL: web, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 8211`,
      cwd: root,
      url: `${api}/health`,
      reuseExistingServer: false,
      env,
      timeout: 60_000,
    },
    {
      command: "pnpm exec next build && pnpm exec next start --port 3211",
      url: `${web}/extraction-runs`,
      reuseExistingServer: false,
      env,
      timeout: 240_000,
    },
  ],
});
