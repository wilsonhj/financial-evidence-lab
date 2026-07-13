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
);
