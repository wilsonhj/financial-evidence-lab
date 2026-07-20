import { HttpObservatorySource } from "./http-source";
import { mockObservatorySource } from "./mock-source";
import type { ObservatoryQuerySource } from "./query-source";
import { loadObservatoryRuntimeConfig } from "./runtime-config";

/**
 * Server-only binding selected explicitly at request time. Keeping environment
 * access out of the client-importable modules prevents bearer-token
 * configuration from being reachable by a client component, and fails closed:
 * an unset FEL_EVIDENCE_SOURCE throws instead of defaulting to fixtures.
 */
export function getObservatorySource(): ObservatoryQuerySource {
  const config = loadObservatoryRuntimeConfig();
  if (config.mode === "mock") return mockObservatorySource;
  return new HttpObservatorySource({
    baseUrl: config.baseUrl,
    workspaceId: config.workspaceId,
    token: config.token,
  });
}
