import type { EvidenceSource } from "./evidence-source";
import { fixtureEvidenceSource } from "./fixture-source";
import { HttpEvidenceSource } from "./http-source";
import { loadEvidenceRuntimeConfig } from "./runtime-config";

/**
 * Server-only binding selected explicitly at request time. Keeping environment
 * access out of data/index.ts prevents bearer-token configuration from being
 * reachable by client components.
 */
export function getEvidenceSource(): EvidenceSource {
  const config = loadEvidenceRuntimeConfig();
  if (config.mode === "fixture") return fixtureEvidenceSource;
  return new HttpEvidenceSource({
    baseUrl: config.baseUrl,
    entityIds: config.entityIds,
    token: config.token,
    asOf: config.asOf,
    corpusVersionId: config.corpusVersionId,
  });
}
