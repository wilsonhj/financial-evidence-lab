import { fixtureEvidenceSource } from "./fixture-source";
import type { EvidenceSource } from "./evidence-source";

export type { EvidenceSource } from "./evidence-source";
export { FixtureEvidenceSource, fixtureEvidenceSource } from "./fixture-source";
export { HttpEvidenceSource } from "./http-source";

/**
 * The evidence source the app is currently wired to. Swap this binding to an
 * HttpEvidenceSource once the ingestion API (M1-INGESTION) publishes section,
 * span, and fact endpoints; no UI code changes are required.
 */
export const evidenceSource: EvidenceSource = fixtureEvidenceSource;
