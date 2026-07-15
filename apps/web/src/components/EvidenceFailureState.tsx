import { RetryEvidenceButton } from "./RetryEvidenceButton";

export type EvidenceFailureStateKind =
  | "authentication"
  | "forbidden"
  | "conflict"
  | "invalid_scope"
  | "unavailable"
  | "configuration"
  | "integrity";

const COPY: Record<
  EvidenceFailureStateKind,
  { heading: string; description: string; retry: boolean }
> = {
  authentication: {
    heading: "Sign in required",
    description:
      "Your evidence session is missing or expired. Sign in again, then reopen this filing.",
    retry: false,
  },
  forbidden: {
    heading: "Access denied",
    description: "Your account does not have access to this evidence corpus.",
    retry: false,
  },
  conflict: {
    heading: "Evidence snapshot changed",
    description: "The requested corpus snapshot could not be read consistently. Retry the request.",
    retry: true,
  },
  invalid_scope: {
    heading: "Invalid evidence scope",
    description: "The configured cutoff or corpus selection is not valid for this request.",
    retry: false,
  },
  unavailable: {
    heading: "Evidence service unavailable",
    description: "The filing may still exist, but the evidence service could not be reached.",
    retry: true,
  },
  configuration: {
    heading: "Evidence source is not configured",
    description: "This deployment has no complete, explicit evidence-source configuration.",
    retry: false,
  },
  integrity: {
    heading: "Evidence response rejected",
    description: "The service returned evidence that did not match the frozen reader contract.",
    retry: true,
  },
};

/** Public-safe state: never renders API messages, details, tokens, or envelopes. */
export function EvidenceFailureState({ kind }: { kind: EvidenceFailureStateKind }) {
  const copy = COPY[kind];
  return (
    <main className="page-main" role="alert" aria-labelledby="evidence-failure-heading">
      <h2 id="evidence-failure-heading">{copy.heading}</h2>
      <p>{copy.description}</p>
      {copy.retry && <RetryEvidenceButton />}
    </main>
  );
}
