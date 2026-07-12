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
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
