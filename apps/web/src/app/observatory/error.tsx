"use client";

/**
 * Error boundary for Observatory routes: query-source failures that are not a
 * typed, public-safe failure state (network faults, unexpected errors) land
 * here instead of crashing the segment.
 */
export default function ObservatoryError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="page-main" role="alert" aria-labelledby="observatory-error-heading">
      <h2 id="observatory-error-heading">Could not load this retrieval run</h2>
      <p>The Observatory failed while loading this run. This is a data-source error.</p>
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
