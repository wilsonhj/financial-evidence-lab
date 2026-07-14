import { join } from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @fel/contracts ships TypeScript source (main: src/index.ts); transpile it
  // inside the Next build instead of requiring a prebuilt dist.
  transpilePackages: ["@fel/contracts"],
  // Pin the workspace root so Turbopack does not infer a parent checkout.
  turbopack: {
    root: join(import.meta.dirname, "../.."),
  },
};

export default nextConfig;
