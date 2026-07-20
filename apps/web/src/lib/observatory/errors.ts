import type { components } from "@fel/contracts";

import type { EvidenceFailureStateKind } from "../../components/EvidenceFailureState";

export type ErrorEnvelope = components["schemas"]["Error"];

/**
 * Safe, UI-facing classification of an Observatory API or transport failure.
 * The kind union deliberately matches the reader's EvidenceFailureKind so the
 * shared EvidenceFailureState component renders both surfaces identically.
 */
export type ObservatoryFailureKind =
  "authentication" | "forbidden" | "conflict" | "invalid_scope" | "unavailable";

export class ObservatoryApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly kind: ObservatoryFailureKind;
  readonly code?: string;
  readonly requestId?: string;

  constructor(
    status: number,
    path: string,
    kind: ObservatoryFailureKind,
    envelope?: ErrorEnvelope,
  ) {
    // Deliberately exclude upstream message/details and request headers. Those
    // may contain sensitive implementation context and must never render.
    super(`Observatory request failed (${kind}, HTTP ${status || "transport"})`);
    this.name = "ObservatoryApiError";
    this.status = status;
    this.path = path;
    this.kind = kind;
    this.code = envelope?.error.code;
    this.requestId = envelope?.error.request_id;
  }
}

/** The API returned 2xx JSON that violates the frozen ADR-0006 trace contract. */
export class ObservatoryContractError extends Error {
  constructor(reason: string) {
    super(`Observatory response failed contract validation: ${reason}`);
    this.name = "ObservatoryContractError";
  }
}

export function observatoryFailureKind(status: number): ObservatoryFailureKind {
  if (status === 401) return "authentication";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 422) return "invalid_scope";
  return "unavailable";
}

/** Maps any thrown Observatory error to the shared public-safe failure state. */
export function observatoryFailureState(error: unknown): EvidenceFailureStateKind | null {
  if (error instanceof ObservatoryApiError) return error.kind;
  if (error instanceof ObservatoryContractError) return "integrity";
  return null;
}

export function parseErrorEnvelope(value: unknown): ErrorEnvelope | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const root = value as Record<string, unknown>;
  if (typeof root.error !== "object" || root.error === null) return undefined;
  const error = root.error as Record<string, unknown>;
  if (
    typeof error.code === "string" &&
    typeof error.message === "string" &&
    typeof error.request_id === "string"
  ) {
    return value as ErrorEnvelope;
  }
  return undefined;
}
