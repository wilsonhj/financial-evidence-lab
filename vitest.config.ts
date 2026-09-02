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
      // On by default so `pnpm run test` — the command CI runs — enforces the
      // floors. The v8 provider adds about a second to the workspace run.
      enabled: true,
      provider: "v8",
      reporter: ["text-summary"],
      // Only files the suites actually load are measured; a floor over every
      // file in the workspace would be a different (much larger) project.
      // Floors are the measured baseline minus one point. Raise them when
      // coverage rises; never lower one without saying why in the PR.
      thresholds: {
        statements: 87.7,
        branches: 78.6,
        functions: 91.2,
        lines: 89.3,
      },
    },
  },
});
