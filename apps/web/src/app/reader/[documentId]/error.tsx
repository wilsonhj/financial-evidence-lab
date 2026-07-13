"use client";

/**
 * Error boundary for the reader route: evidence-source failures that are NOT
 * "document does not exist" (network faults, API 5xx, auth problems —
 * EvidenceApiError and friends) land here as a real error state instead of
 * being misreported as a 404.
 */
export default function ReaderError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="page-main" role="alert" aria-labelledby="reader-error-heading">
      <h2 id="reader-error-heading">Could not load this filing</h2>
      <p>
        The evidence source failed while loading this document. The document may still exist — this
        is a data-source error, not a missing filing.
      </p>
      {error.digest && (
        <p style={{ color: "var(--color-muted)", fontSize: "0.85rem" }}>
          Error reference: {error.digest}
        </p>
      )}
      <button type="button" className="retry-button" onClick={() => reset()}>
        Try again
      </button>
    </main>
  );
}
