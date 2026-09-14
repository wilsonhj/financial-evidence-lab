import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const manifestPath = process.env.READER_SMOKE_MANIFEST;
if (!manifestPath) throw new Error("READER_SMOKE_MANIFEST is required");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const hosted = process.env.READER_SMOKE_HOSTED === "1";
const api = process.env.READER_SMOKE_API_URL ?? "http://127.0.0.1:8218";
const web = process.env.READER_SMOKE_WEB_URL ?? "http://127.0.0.1:3218";
if (hosted && (!api.startsWith("https://") || !web.startsWith("https://"))) {
  throw new Error("Hosted smoke requires explicit HTTPS API and web URLs");
}
const quote = (value: string) => "'" + value.replaceAll("'", "'\"'\"'") + "'";
const root = fileURLToPath(new URL("../..", import.meta.url));
const token = `mock.${Buffer.from(JSON.stringify({ org_id: manifest.org, sub: manifest.user, role: "owner" })).toString("base64url")}`;
const env = {
  FEL_AUTH_MODE: "mock",
  FEL_EVIDENCE_SOURCE: "http",
  FEL_API_BASE_URL: api,
  FEL_API_BEARER_TOKEN: token,
  FEL_WORKSPACE_ID: manifest.workspace,
  FEL_ENTITY_IDS: manifest.entity,
  FEL_AS_OF: manifest.as_of,
};
export default defineConfig({
  testDir: "./e2e",
  testMatch: "reader-prod-smoke.acceptance.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["json", { outputFile: "test-results/reader-prod-smoke.json" }]],
  // Authenticated API requests are deliberately excluded from traces/HAR.
  use: { baseURL: web, trace: "off", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: hosted
    ? undefined
    : [
        {
          command: `${quote(process.env.FEL_ACCEPTANCE_PYTHON ?? "python")} -m evals.harness.reader_prod_smoke_service serve --manifest ${quote(manifestPath)} --dedicated-target ${quote(process.env.FEL_READER_SMOKE_TARGET ?? "")}`,
          cwd: root,
          url: `${api}/health`,
          reuseExistingServer: false,
          env,
          timeout: 60_000,
        },
        {
          command: "pnpm exec next build && pnpm exec next start --port 3218",
          url: `${web}/`,
          reuseExistingServer: false,
          env,
          timeout: 240_000,
        },
      ],
});
