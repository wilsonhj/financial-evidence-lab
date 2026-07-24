import { defineConfig, devices } from "@playwright/test";

// Dedicated port so a running `next dev` (3000) never collides with the E2E
// server. The suite drives the Observatory in fixture mode only: the mock
// source is deterministic and never reaches the network, so runs are stable.
const PORT = 3210;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Production build + start is more deterministic than `next dev`, whose
    // first-hit route compilation can slow or flake under CI load.
    command: `pnpm exec next build && pnpm exec next start --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      // Fixture mode binds both the Observatory mock source and the reader
      // evidence source to the committed synthetic trace/filing — no network,
      // no bearer token. This is the only env the suite needs.
      FEL_EVIDENCE_SOURCE: "fixture",
    },
  },
});
