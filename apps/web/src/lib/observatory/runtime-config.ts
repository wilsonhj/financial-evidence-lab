import { env as serverEnvironment } from "node:process";

// The Node-only import is deliberate: a future Client Component import fails at
// build time instead of pulling secret-backed configuration into its graph.

import { EvidenceConfigurationError } from "../data/runtime-config";

export type ObservatoryRuntimeConfig =
  { mode: "mock" } | { mode: "http"; baseUrl: string; token: string; workspaceId: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function required(env: Readonly<Record<string, string | undefined>>, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new EvidenceConfigurationError(`HTTP evidence mode requires ${name}`);
  return value;
}

/**
 * Parses only server runtime variables. Never import this module from a client
 * component. Binds to the same FEL_EVIDENCE_SOURCE switch as the reader so a
 * deployment cannot serve live reader evidence while the Observatory silently
 * falls back to fixtures (or vice versa).
 */
export function loadObservatoryRuntimeConfig(
  env: Readonly<Record<string, string | undefined>> = serverEnvironment,
): ObservatoryRuntimeConfig {
  const mode = env.FEL_EVIDENCE_SOURCE?.trim();
  if (mode === "fixture") return { mode: "mock" };
  if (mode !== "http") {
    throw new EvidenceConfigurationError(
      "FEL_EVIDENCE_SOURCE must be explicitly set to fixture or http",
    );
  }

  const rawBaseUrl = required(env, "FEL_API_BASE_URL");
  let url: URL;
  try {
    url = new URL(rawBaseUrl);
  } catch {
    throw new EvidenceConfigurationError("FEL_API_BASE_URL must be an absolute HTTP(S) URL");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new EvidenceConfigurationError(
      "FEL_API_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment",
    );
  }
  const loopback = ["localhost", "127.0.0.1", "::1"].includes(url.hostname);
  if (env.NODE_ENV === "production" && url.protocol !== "https:" && !loopback) {
    throw new EvidenceConfigurationError(
      "FEL_API_BASE_URL must use HTTPS outside local development",
    );
  }

  const workspaceId = required(env, "FEL_WORKSPACE_ID");
  if (!UUID.test(workspaceId)) {
    throw new EvidenceConfigurationError("FEL_WORKSPACE_ID must be a UUID");
  }

  return {
    mode,
    baseUrl: url.toString().replace(/\/$/, ""),
    token: required(env, "FEL_API_BEARER_TOKEN"),
    workspaceId,
  };
}
