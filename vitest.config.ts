import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: [
      "apps/**/*.test.ts",
      "apps/**/*.test.tsx",
      "packages/**/*.test.ts",
      "scripts/**/*.test.mjs",
    ],
    environment: "node",
    coverage: {
      provider: "v8",
      include: ["apps/*/src/**/*.{ts,tsx}", "packages/*/src/**/*.{ts,tsx}", "scripts/*.mjs"],
      exclude: ["**/*.test.{ts,tsx,mjs}", "**/*.d.ts", "**/generated/**", "**/test-support/**"],
      reporter: ["text", "json-summary"],
      thresholds: { statements: 85.08, branches: 76.15, functions: 82.89, lines: 86.33 },
    },
  },
});
