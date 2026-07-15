import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/.next/**",
      "**/node_modules/**",
      "**/coverage/**",
      ".venv/**",
      ".claude/**",
      "packages/contracts/src/generated/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    // Node runtime scripts (run via `node scripts/...`): declare the Node
    // globals the recommended browser-agnostic config doesn't provide.
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      globals: {
        console: "readonly",
        process: "readonly",
        fetch: "readonly",
        URL: "readonly",
      },
    },
  },
);
