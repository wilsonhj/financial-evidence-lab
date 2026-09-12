import Link from "next/link";
import type { ReactNode } from "react";
import type { Proposal } from "../../lib/extraction/contracts";

export function ExtractionShell({
  title,
  mode,
  children,
}: {
  title: string;
  mode?: "fixture" | "http";
  children: ReactNode;
}) {
  return (
    <main id="main-content" className="page-main" tabIndex={-1}>
      <nav aria-label="Extraction navigation">
        <Link href="/desk">Desk</Link>
        {" · "}
        <Link href="/extractions">Review queue</Link>
        {" · "}
        <Link href="/extraction-runs">Run history</Link>
      </nav>
      <h1>{title}</h1>
      {mode === "fixture" && (
        <p role="note">
          Synthetic fixture mode. These examples do not establish financial validity or live
          execution.
        </p>
      )}
      {children}
    </main>
  );
}
export function PayloadFields({ payload }: { payload: Proposal["payload"] }) {
  const candidate = payload.schema_version === "extraction-candidate-fields/v1";
  const fields = candidate ? payload.fields : payload;
  return (
    <section aria-label="Financial fields">
      <h2>{candidate ? "Read-only candidate fields" : "Recorded financial fields"}</h2>
      {candidate && (
        <p>
          Persisted JSON text. Missing fields are absent; the text null represents a present JSON
          null. Full edits require an explicit strict replacement.
        </p>
      )}
      <dl>
        {Object.entries(fields).map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>
              <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                {candidate
                  ? value
                  : typeof value === "string"
                    ? value
                    : JSON.stringify(value, null, 2)}
              </pre>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
export function ProposalStatus({ proposal }: { proposal: Proposal }) {
  return (
    <section aria-label="Validation and confidence">
      <p>
        State: {proposal.state} · Version {proposal.version} · Priority: {proposal.review_priority}
      </p>
      <p>Record confidence: {proposal.record_confidence ?? "Uncalibrated"}</p>
      {Object.keys(proposal.field_confidences).length > 0 && (
        <dl>
          {Object.entries(proposal.field_confidences).map(([field, score]) => (
            <div key={field}>
              <dt>{field}</dt>
              <dd>{score}</dd>
            </div>
          ))}
        </dl>
      )}
      <ul>
        {proposal.validations.map((v, index) => (
          <li key={`${v.code}-${index}`}>
            {v.status}: {v.code}
          </li>
        ))}
      </ul>
      {!proposal.validations.length && <p>No validation results recorded.</p>}
      {!proposal.evidence.length && (
        <p role="note">No evidence edges recorded. Approval still requires verified evidence.</p>
      )}
    </section>
  );
}
export function ExtractionPagination({
  path,
  query = {},
  page,
}: {
  path: string;
  query?: Record<string, string>;
  page: { next_cursor: string | null; previous_cursor: string | null; limit: number };
}) {
  const link = (cursor: string) =>
    `${path}?${new URLSearchParams({ ...query, limit: String(page.limit), cursor })}`;
  return (
    <nav aria-label="Extraction pages">
      {page.previous_cursor ? (
        <Link href={link(page.previous_cursor)}>Previous page</Link>
      ) : (
        <span aria-disabled="true">Previous page</span>
      )}
      {" · "}
      {page.next_cursor ? (
        <Link href={link(page.next_cursor)}>Next page</Link>
      ) : (
        <span aria-disabled="true">Next page</span>
      )}
    </nav>
  );
}
export function ExtractionError() {
  return (
    <section role="alert">
      <h2>Extraction view unavailable</h2>
      <p>
        Check the selected source configuration, your access and the requested scope. No fixture
        fallback was used.
      </p>
      <Link href="/extractions">Return to review queue</Link>
    </section>
  );
}
