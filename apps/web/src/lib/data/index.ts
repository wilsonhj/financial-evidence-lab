import { fixtureEvidenceSource } from "./fixture-source";
import type { EvidenceSource } from "./evidence-source";

export type { EvidenceSource, EvidenceSourceCapabilities } from "./evidence-source";
export { FixtureEvidenceSource, fixtureEvidenceSource } from "./fixture-source";
export { EvidenceApiError, HttpEvidenceSource } from "./http-source";
export type { BearerTokenProvider, ErrorEnvelope, HttpEvidenceSourceOptions } from "./http-source";

/**
 * The evidence source the app is currently wired to. Swap this binding to an
 * HttpEvidenceSource (baseUrl + entityIds + bearer token, optional asOf) once
 * the ingestion API (M1-INGESTION) publishes section, span, and fact
 * endpoints. Until then the HTTP source advertises
 * `capabilities: { sections: false, spans: false, facts: false }` and the
 * reader page renders a graceful "details not yet available" state for it —
 * only document listing/detail work over HTTP today.
 */
export const evidenceSource: EvidenceSource = fixtureEvidenceSource;
